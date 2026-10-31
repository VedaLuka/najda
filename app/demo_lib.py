"""Shared, Streamlit-free helpers for the demo dashboard: load app/data/, turn a doctor trajectory into timeline
events, and compute the right-hand panel state (checklist, config diff, counters) after k events.

Everything here is pure Python so tests can import it without Streamlit.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

DATA = Path(__file__).resolve().parent / "data"

NAVY, AMBER, TEAL = "#0B1B2B", "#FFB020", "#19C2A0"
RED, GREY, INK = "#FF5C5C", "#8DA2B5", "#F3F6F9"

INVARIANT_LABELS: dict[str, dict[str, str]] = {
    "order": {
        "total_matches_menu": "Totals match the menu (SAR)",
        "qty_matches_request": "Quantities match the customer",
        "confirmed_has_payment": "Confirmed ⇒ paid",
        "payment_has_confirmed_order": "Paid ⇒ confirmed",
        "reply_matches_ledger": "Bot's reply matches the ledger",
        "turns_under_cap": "Turns under the hard cap",
        "no_unhandled_error": "No unhandled errors",
    },
    "hajz": {
        "confirmed_has_deposit": "Confirmed ⇒ deposit paid",
        "deposit_has_confirmed_booking": "Deposit ⇒ confirmed booking",
        "deposit_charged_once": "Deposit charged once",
        "deposit_matches_party": "Deposit matches party size",
        "booking_time_matches_request": "Booking time matches the customer",
        "no_double_booking": "No double booking",
        "reply_matches_ledger": "Bot's reply matches the ledger",
        "turns_under_cap": "Turns under the hard cap",
        "no_unhandled_error": "No unhandled errors",
    },
}
READ_ACTIONS = ("read_traces", "read_metrics", "read_invariants", "read_chats", "read_config", "config_history_diff")


# ------------------------------------------------ loading ------------------------------------------------

def load_json(rel: str) -> Any:
    return json.loads((DATA / rel).read_text(encoding="utf-8"))


def manifest() -> dict[str, Any]:
    return load_json("manifest.json")


def incident(incident_id: str) -> dict[str, Any]:
    return load_json(f"incidents/{incident_id}.json")


def repeat() -> dict[str, Any]:
    return load_json("repeat.json")


def sections(doc: str) -> list[dict[str, str]]:
    return load_json("results/sections.json")[doc]


def section(doc: str, heading_prefix: str, nth: int = 0) -> str:
    hits = [s["body"] for s in sections(doc) if s["heading"].startswith(heading_prefix)]
    return hits[nth] if len(hits) > nth else ""


def read_csv(name: str) -> list[dict[str, str]]:
    with (DATA / "results" / name).open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# ------------------------------------------------ timeline ------------------------------------------------

def _patch_text(patch: dict[str, Any]) -> str:
    return ", ".join(f"{k} → {json.dumps(v, ensure_ascii=False)}" for k, v in patch.items()) or "(no change)"


def build_timeline(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse raw doctor steps into presentable events. Consecutive evidence reads become one event."""
    events: list[dict[str, Any]] = []
    reads: list[str] = []

    def flush_reads() -> None:
        if reads:
            events.append({"kind": "evidence", "title": "Reads the incident bundle", "chips": reads[:], "t": None})
            reads.clear()

    for s in steps:
        a, r, args = s["action"], s.get("result") or {}, s.get("args") or {}
        if a in READ_ACTIONS:
            label = a.replace("read_", "").replace("_", " ")
            if a == "read_traces" and args.get("errors_only"):
                label = "error traces"
            reads.append(label)
            continue
        ev: dict[str, Any] = {"kind": a, "title": a, "t": s.get("t"), "raw": r}
        if a == "replay" and args.get("config_version") == 1 and args.get("chats") == "failed":
            ev.update(kind="baseline", title="Baseline replay of the failed chats",
                      body=f"{r['n_pass']}/{r['n_total']} pass · violations: {', '.join(r.get('violations') or []) or 'none'}")
        elif a == "replay":
            chats = args.get("chats")
            scope = "failed chats" if chats == "failed" else f"{len(chats)} chats" if isinstance(chats, list) else str(chats)
            ev.update(kind="replay", title=f"Replay on config v{args.get('config_version')} ({scope})",
                      body=f"{r['n_pass']}/{r['n_total']} pass", ok=bool(r.get("all_pass")))
        elif a == "najda.baseline_replay":
            continue
        elif a == "najda.money_at_risk":
            if r.get("evidence"):
                ev.update(kind="money", title="Money at risk", body="; ".join(r["evidence"][:3]))
            else:
                continue
        elif a == "najda.freeze":
            ev.update(kind="freeze", title="CHANGE FREEZE: payment upstream is failing",
                      body="No config change is allowed until a human looks. " + "; ".join(r.get("evidence", [])[:3]))
        elif a == "najda.bisect":
            if r.get("applicable"):
                ev.update(kind="bisect", title="Bisect over config history",
                          body=f"culprit version {r.get('culprit')} · tested {len(r.get('tested', []))} versions")
            else:
                ev.update(kind="bisect", title="Bisect over config history", body=f"not applicable: {r.get('reason')}")
        elif a == "najda.playbook":
            e = r.get("event")
            if e == "miss":
                ev.update(kind="playbook", title="Memory: no matching playbook", body="new fault → full investigation")
            elif e == "match":
                ev.update(kind="playbook_hit", title=f"Memory: playbook {r.get('id')} matches (tier {r.get('tier')}, score {r.get('score', 1):.2f})",
                          body=f"learned on {r.get('source_incident')} · proposes {_patch_text(r['patches'][0]) if r.get('patches') else 'escalate'}")
            elif e == "learned":
                ev.update(kind="learned", title=f"Memory: playbook {r.get('id')} learned ({r.get('kind')})",
                          body="next time this signature appears, no big-model call is needed")
            elif e == "hit":
                ev.update(kind="playbook_hit", title="Memory: playbook verified end to end", body=f"{r.get('llm_calls', 0)} LLM calls")
            else:
                continue
        elif a == "llm":
            role, model = args.get("role"), args.get("model", "")
            ev.update(kind="llm", title=f"LLM call: {args.get('purpose', role)} ({model})",
                      body=f"{r.get('input_tokens', 0):,} in · {r.get('output_tokens', 0):,} out · ${r.get('cost_usd', 0):.4f}"
                           + (f" · tools: {', '.join(r['tool_calls'])}" if r.get("tool_calls") else ""),
                      cost=r.get("cost_usd", 0.0))
        elif a == "najda.triage":
            ev.update(kind="triage", title=f"Triage brief: {r.get('class')}", body=r.get("brief") or "no known pattern; investigate")
        elif a == "najda.turn":
            if not r.get("text"):
                continue
            ev.update(kind="turn", title="Investigator's note", body=r["text"])
        elif a == "najda.hypotheses":
            ev.update(kind="hypotheses", title="Ranked hypotheses", ranked=r.get("ranked", []),
                      escalate=bool(r.get("escalate_recommended")))
        elif a == "najda.guardrail":
            ev.update(kind="guardrail", title="Guardrail verdict", allowed=bool(r.get("allowed")), rule=r.get("rule"),
                      body=f"{_patch_text(r.get('patch', {}))} · {r.get('reason')}")
        elif a == "apply_patch":
            ev.update(kind="patch", title=f"Apply patch → config v{r.get('version')}", body=_patch_text(args.get("patch", {})),
                      patch=args.get("patch", {}))
        elif a == "rollback":
            ev.update(kind="rollback", title="Rollback", body=str(r)[:200])
        elif a == "najda.canary":
            ev.update(kind="canary", title="Canary replay", ok=bool(r.get("passed")),
                      body=f"{r.get('n_pass')}/{len(r.get('chats', []))} canary chats pass ({', '.join(r.get('chats', []))})")
        elif a == "najda.regression_check":
            ev.update(kind="regression", title="Regression replay of chats that were passing",
                      body=f"checked {r.get('checked')} · broke {len(r.get('broke', []))}", ok=not r.get("broke"))
        elif a == "najda.verify":
            ok = r.get("status") == "verified"
            ev.update(kind="verify", title=f"Verify: {r.get('status')}", ok=ok,
                      body=f"{r.get('n_pass')}/{r.get('n_total')} failed chats now pass" + (f" · remaining {r['remaining']}" if r.get("remaining") else ""))
        elif a == "najda.decision":
            ev.update(kind="decision", title=f"Decision: {r.get('status')}", body=f"root cause {r.get('label')} · kept config v{r.get('kept_version')}",
                      status=r.get("status"))
        elif a == "escalate":
            ev.update(kind="escalate", title="Escalate to a human", body=(args.get("report") or "").split("\n")[0][:200])
        else:
            continue
        flush_reads()
        events.append(ev)
    flush_reads()
    return events


# ------------------------------------------------ panel state ------------------------------------------------

def lookup(cfg: dict[str, Any], dotted: str) -> Any:
    cur: Any = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def panel_state(inc: dict[str, Any], events: list[dict[str, Any]], k: int, traj: dict[str, Any]) -> dict[str, Any]:
    """Checklist, config diff and counters after the first k events."""
    shown = events[:k]
    patient = inc.get("patient", "order")
    labels = INVARIANT_LABELS.get(patient, INVARIANT_LABELS["order"])
    violated = {v["invariant"] for v in inc["bundle"]["invariants"]}
    verified = any(e["kind"] == "verify" and e.get("ok") for e in shown)
    frozen = any(e["kind"] == "freeze" for e in shown)
    escalated = any(e["kind"] == "escalate" or (e["kind"] == "decision" and e.get("status") == "escalated") for e in shown)
    baseline = next((e for e in shown if e["kind"] == "baseline"), None)
    n_total = baseline["raw"]["n_total"] if baseline else inc["bundle"]["metrics"].get("chats_failed", 0)
    n_pass = next((e["raw"]["n_pass"] for e in reversed(shown) if e["kind"] in ("verify",) and e.get("ok")), 0)

    checklist = [{"label": labels.get(name, name), "ok": verified, "was_broken": True} for name in sorted(violated)]
    checklist += [{"label": labels.get(name, name), "ok": True, "was_broken": False} for name in labels if name not in violated]
    served = {"label": f"Failed chats recovered ({n_pass}/{n_total})", "ok": verified and n_pass == n_total, "was_broken": n_total > 0}

    cfg0 = inc["bundle"]["config"]["current"]
    diff = []
    for e in shown:
        if e["kind"] == "patch":
            for key, after in e["patch"].items():
                diff.append({"knob": key, "before": lookup(cfg0, key), "after": after})
    rolled_back = any(e["kind"] == "rollback" for e in shown)

    llm_calls = sum(1 for e in shown if e["kind"] == "llm")
    cost = sum(e.get("cost", 0.0) for e in shown if e["kind"] == "llm")
    t_last = next((e["t"] for e in reversed(shown) if e.get("t") is not None), 0.0) or 0.0
    t_end = next((e["t"] for e in reversed(events) if e.get("t") is not None), 0.0) or 0.0
    wall = traj.get("recorded", {}).get("scores", {}).get("wall_s") or traj.get("wall_s") or 0.0
    elapsed = wall * (t_last / t_end) if t_end else 0.0
    return {"checklist": checklist, "served": served, "diff": diff, "rolled_back": rolled_back, "frozen": frozen,
            "escalated": escalated, "verified": verified, "llm_calls": llm_calls, "cost": cost, "elapsed_s": elapsed,
            "done": k >= len(events)}


def split_report(report: str) -> dict[str, str]:
    """The bilingual first line ('AR | EN') plus the named sections of a Najda report."""
    lines = report.strip().split("\n")
    first = lines[0] if lines else ""
    ar, _, en = first.partition(" | ")
    out = {"ar": ar.strip(), "en": en.strip(), "rest": "\n".join(lines[1:]).strip()}
    for key in ("Summary", "Impact", "Recommended human action"):
        for ln in lines[1:]:
            if ln.startswith(key + ":"):
                out[key] = ln.split(":", 1)[1].strip()
    return out


def failing_chats(inc: dict[str, Any]) -> list[dict[str, Any]]:
    """Chats that violated an invariant or failed outright, in bundle order."""
    bad = {v["chat_id"] for v in inc["bundle"]["invariants"]}
    bad |= {c["chat_id"] for c in inc["bundle"]["chats"] if c["outcome"] == "failed"}
    return [c for c in inc["bundle"]["chats"] if c["chat_id"] in bad]


def table_rows(md: str) -> list[list[str]]:
    """Cells of the first markdown table in `md`, header and separator excluded."""
    rows = [ln for ln in md.splitlines() if ln.startswith("|")]
    out = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in rows]
    return [r for r in out[1:] if not all(set(c) <= set("-: ") for c in r)]
