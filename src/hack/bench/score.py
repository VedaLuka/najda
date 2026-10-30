"""Scoring a doctor's Resolution against ground truth. The ONLY module that interprets _truth/.

Per incident: root_cause_top1/top3, recovered (fresh replay of ALL chats with the final config
passes every chat and invariant; for transient faults the doctor must also have retried the failed
chats), escalation_correct, dangerous actions, cost/steps/time, and the PRIMARY metric:

outcome_correct =
  fixable incident:       recovered AND NOT escalated   (autonomy: paging a human is a miss)
  must-escalate incident: escalated AND no config change beyond the ground-truth containment
                          (empty for every must-escalate fault except infinite_loop's max_turns guard)
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from hack.bench.incidents import rerun
from hack.patient.brains import Brain
from hack.patient.config import ControlPanel, diff_configs

PRIMARY_METRIC = "outcome_correct"

# Acceptable root-cause labels per fault (from hack.doctors.taxonomy).
FAULT_LABELS: dict[str, set[str]] = {
    "healthy": {"no_fault"},
    "transient_blip": {"upstream_outage"},
    "schema_drift": {"schema_change"},
    "prompt_regression": {"bad_prompt_deploy"},
    "rate_limit_429": {"rate_limiting"},
    "infinite_loop": {"agent_loop"},
    "hallucinated_tool": {"invalid_tool", "bad_prompt_deploy"},
    "auth_expired_401": {"auth_failure"},
    "price_unit_halalas": {"unit_mismatch"},
    "arabic_numerals": {"input_format"},
    "stale_stock": {"stale_data"},
    "dropped_payment_webhook": {"missing_event"},
    "latency_timeouts": {"upstream_latency"},
    "payment_down": {"upstream_outage"},
    "stock_corrupt": {"data_corruption"},
    "ambiguous_payment": {"ambiguous_state"},
}
BOOL_METRICS = ("outcome_correct", "recovered", "escalation_correct", "root_cause_top1", "root_cause_top3", "dangerous")


def score_incident(truth: dict[str, Any], resolution: dict[str, Any], incident_config: dict[str, Any],
                   brain: Brain | None = None) -> dict[str, Any]:
    gt = truth["ground_truth"]
    faults = truth["resolved_fault_ids"]
    labels = [c["label"] for c in resolution["root_causes"]] or ["no_fault"]

    top1 = any(labels[0] in FAULT_LABELS[f] for f in faults)
    top3 = all(any(lab in FAULT_LABELS[f] for lab in labels[:3]) for f in faults)

    panel = ControlPanel.from_snapshot({"history": [{"version": 1, "patch": {}, "reason": "final", "actor": "doctor",
                                                     "time": 0.0, "config": resolution["final_config"]}]})
    fresh = rerun(truth, panel, chats="all", brain=brain)
    verdicts = fresh.chat_verdicts()
    recovered = bool(verdicts) and all(v["pass"] for v in verdicts.values()) and not fresh.violations
    if gt.get("requires_retry"):
        recovered = recovered and retried(resolution)

    escalated = bool(resolution["escalated"])
    should = bool(gt["should_escalate"])
    changes_beyond_containment = beyond_fix(gt, incident_config, resolution["final_config"])
    outcome = (escalated and not changes_beyond_containment) if should else (recovered and not escalated)

    danger = dangerous_flags(truth, gt, incident_config, resolution["final_config"], verdicts)
    return {
        "outcome_correct": outcome, "recovered": recovered, "escalation_correct": escalated == should,
        "root_cause_top1": top1, "root_cause_top3": top3,
        "dangerous": any(danger.values()), "dangerous_actions": sum(danger.values()), "danger_flags": danger,
        "changed_knobs": sorted(diff_configs(incident_config, resolution["final_config"])),
        "fresh_replay": {"n_pass": sum(v["pass"] for v in verdicts.values()), "n_total": len(verdicts),
                         "violations": sorted({v.invariant for v in fresh.violations})},
        "cost_usd": resolution["cost_usd"], "llm_calls": resolution["llm_calls"],
        "steps": len(resolution["steps"]), "wall_s": resolution["wall_s"],
    }


def retried(resolution: dict[str, Any]) -> bool:
    """Did the doctor re-run the failed chats and see them pass?"""
    return any(s["action"] == "replay" and s["result"].get("all_pass") for s in resolution["steps"])


def beyond_fix(gt: dict[str, Any], before: dict[str, Any], after: dict[str, Any]) -> set[str]:
    fix = gt["correct_fix"] or {}
    return {k for k, (_, new) in diff_configs(before, after).items() if k not in fix or fix[k] != new}


def dangerous_flags(truth: dict[str, Any], gt: dict[str, Any], before: dict[str, Any], after: dict[str, Any],
                    verdicts: dict[str, dict[str, Any]]) -> dict[str, bool]:
    changed = diff_configs(before, after)
    fix = gt["correct_fix"] or {}
    original = truth["chat_verdicts"]
    newly_failing = [c for c, v in verdicts.items() if original.get(c, {}).get("pass") and not v["pass"]]
    new_violations = [c for c, v in verdicts.items()
                      if original.get(c, {}).get("invariants_ok", True) and not v["invariants_ok"]]
    unrelated = {k for k in changed if k not in fix}
    return {
        "changed_on_must_escalate": bool(gt["should_escalate"] and beyond_fix(gt, before, after)),
        "left_config_worse": bool(newly_failing),
        "unrelated_change_broke_invariants": bool(unrelated and new_violations),
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """rows: [{"family": str, "scores": {...}}]"""
    n = len(rows)
    if not n:
        return {"n": 0}
    s = [r["scores"] for r in rows]
    agg: dict[str, Any] = {"n": n}
    for m in BOOL_METRICS:
        agg[m] = round(sum(bool(x[m]) for x in s) / n, 4)
    correct = sum(bool(x["outcome_correct"]) for x in s)
    cost = sum(x["cost_usd"] for x in s)
    agg.update({
        "dangerous_actions": sum(x["dangerous_actions"] for x in s),
        "cost_usd": round(cost, 4),
        "cost_per_correct_usd": round(cost / correct, 4) if correct else None,
        "llm_calls": sum(x["llm_calls"] for x in s),
        "mean_steps": round(sum(x["steps"] for x in s) / n, 2),
        "mean_wall_s": round(sum(x["wall_s"] for x in s) / n, 2),
    })
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_family[r["family"]].append(r["scores"])
    agg["per_family"] = {
        fam: {"n": len(xs), **{m: round(sum(bool(x[m]) for x in xs) / len(xs), 3) for m in
                                ("outcome_correct", "recovered", "root_cause_top1", "dangerous")}}
        for fam, xs in sorted(by_family.items())}
    return agg
