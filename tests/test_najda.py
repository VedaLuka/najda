"""Najda with a scripted fake LLM: guardrails, rollback, budget, containment, grounding, sealed truth."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hack.bench.harness import treat_incident  # noqa: E402
from hack.bench.score import score_incident  # noqa: E402
from hack.bench.seal import truth_sealed  # noqa: E402
from hack.bench.truth import read_truth  # noqa: E402
from hack.doctors import get_doctor  # noqa: E402
from hack.llm import ToolLLMResult  # noqa: E402

DEV = ROOT / "data" / "incidents" / "dev"
SCHEMA, LOOP, PAYMENT_DOWN, HEALTHY, BLIP = "dev-001", "dev-013", "dev-029", "dev-033", "dev-038"


class FakeLLM:
    """Returns scripted assistant turns. Each turn is a list of (tool_name, input); [] = plain text turn."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = 0

    def __call__(self, messages, tools, system):
        self.calls += 1
        turn = self.turns.pop(0) if self.turns else [("search_traces", {"errors_only": True})]
        content = [{"type": "text", "text": "thinking out loud"}]
        for i, (name, args) in enumerate(turn):
            content.append({"type": "tool_use", "id": f"t{self.calls}_{i}", "name": name, "input": args})
        return ToolLLMResult(content, "tool_use" if turn else "end_turn", "fake", 0, 0, 0, 0.0, False, True)


def propose(*hyps, escalate=False, **extra):
    return ("propose_hypotheses", {"hypotheses": [
        {"root_cause": label, "confidence": conf, "evidence_span_ids": spans, "rationale": "r", "patch": patch}
        for label, conf, spans, patch in hyps], "escalate_recommended": escalate, "summary": "s", **extra})


def run(doctor_name, incident, llm, config=None):
    doctor = get_doctor(doctor_name, config)
    doctor.llm_fn = llm
    truth = read_truth(DEV / incident)
    with truth_sealed():
        resolution, initial = treat_incident(doctor, DEV / incident, truth)
    assert resolution.error is None, resolution.error
    return resolution, initial, truth


def failing_span(incident):
    """A tool span id from a failing chat (so hypotheses can be grounded)."""
    from hack.doctors.environment import Environment

    from hack.doctors.najda.diffdiag import differential

    env = Environment(DEV / incident, lambda panel, chats="failed": None)
    diff = differential(env)
    return next(r["examples"][0] for r in diff.rows if r["n_pass"] == 0 and r["examples"])


def test_wrong_patch_is_rolled_back_then_right_patch_verified():
    truth = read_truth(DEV / SCHEMA)
    llm = FakeLLM([[propose(("rate_limiting", 0.9, [failing_span(SCHEMA)], {"retry.max_retries": 3}),
                            ("schema_change", 0.8, [failing_span(SCHEMA)], truth["ground_truth"]["correct_fix"]))]])
    res, initial, truth = run("najda_v1", SCHEMA, llm)
    rolled = [a for a in res.actions if a["type"] == "rollback"]
    assert len(rolled) == 1 and not res.escalated
    assert res.final_config["field_mappings"]["order_id"] == "id"
    assert res.final_config["retry"]["max_retries"] == initial["retry"]["max_retries"]
    assert res.root_causes[0].label == "schema_change"
    assert score_incident(truth, res.to_dict(), initial)["outcome_correct"]


def test_all_patches_fail_means_clean_config_and_escalation():
    llm = FakeLLM([[propose(("rate_limiting", 0.9, [], {"retry.max_retries": 3}))]] * 3)
    res, initial, _ = run("najda_v1", SCHEMA, llm)
    assert res.escalated and res.final_config == initial
    assert "Najda" in res.report and "نجدة" in res.report


def test_guardrail_blocks_protected_knob_when_money_at_risk():
    llm = FakeLLM([[propose(("upstream_outage", 0.9, [failing_span(PAYMENT_DOWN)], {"payment_verify": "query"}),
                            escalate=True)]])
    res, initial, truth = run("najda_v2", PAYMENT_DOWN, llm)
    blocked = [s for s in res.steps if s["action"] == "najda.guardrail" and not s["result"]["allowed"]]
    assert blocked and blocked[0]["result"]["rule"] == "protected_knob_money_at_risk"
    assert not [a for a in res.actions if a["type"] == "patch"]
    assert res.escalated and res.final_config == initial
    assert score_incident(truth, res.to_dict(), initial)["outcome_correct"]


def test_budget_hit_rolls_back_and_escalates():
    llm = FakeLLM([[("apply_patch", {"patch": {"retry.max_retries": 5}, "reason": "guess"})]] + [[("read_metrics", {})]] * 5)
    res, initial, _ = run("najda_v1", SCHEMA, llm, {"max_llm_calls": 3})
    assert any(s["action"] == "najda.budget_hit" for s in res.steps)
    assert res.escalated and res.final_config == initial


def test_containment_is_kept_and_escalated_when_nothing_else_fixes_it():
    span = failing_span(LOOP)
    llm = FakeLLM([[propose(("agent_loop", 0.8, [span], {"max_turns": 10}))],
                   [propose(("agent_loop", 0.8, [span], {}), escalate=True, escalation_reason="upstream stuck")]])
    res, initial, truth = run("najda_v2", LOOP, llm)
    assert res.escalated and res.final_config["max_turns"] == 10
    kept = [s for s in res.steps if s["action"] == "najda.verify"]
    assert kept and kept[0]["result"]["status"] == "kept_improvement"
    assert score_incident(truth, res.to_dict(), initial)["outcome_correct"]


def test_ungrounded_hypothesis_is_rejected_before_any_patch():
    from hack.doctors.environment import Environment

    env = Environment(DEV / SCHEMA, lambda panel, chats="failed": None)
    passing = set(env.passing_chat_ids())
    assert passing, "test needs an incident with passing chats"
    span = next(s["span_id"] for s in env.read_traces(limit=None) if s["attributes"]["chat.id"] in passing)
    llm = FakeLLM([[propose(("schema_change", 0.9, [span], {"field_mappings.order_id": "id"}))]] * 3)
    res, initial, _ = run("najda_v2", SCHEMA, llm)
    hyps = next(s for s in res.steps if s["action"] == "najda.hypotheses")["result"]["ranked"]
    assert hyps[0]["status"] == "ungrounded"
    assert not [a for a in res.actions if a["type"] == "patch"]


def test_healthy_and_transient_incidents_need_no_patch():
    res, initial, truth = run("najda_v2", HEALTHY, FakeLLM([]))
    assert res.root_causes[0].label == "no_fault" and res.llm_calls == 0 and not res.escalated
    llm = FakeLLM([[propose(("upstream_outage", 0.7, [], {}))]])
    res, initial, truth = run("najda_v2", BLIP, llm)
    assert not res.escalated and res.final_config == initial
    assert score_incident(truth, res.to_dict(), initial)["outcome_correct"]


def test_najda_never_touches_truth_while_sealed():
    """treat_incident runs under the seal; any _truth read raises PermissionError and shows up as an error."""
    res, _, _ = run("najda_v2", SCHEMA, FakeLLM([[propose(("schema_change", 0.9, [failing_span(SCHEMA)], {"field_mappings.order_id": "id"}))]]))
    assert res.error is None
    import hack.doctors.najda as pkg
    src = "".join(p.read_text() for p in Path(pkg.__file__).parent.glob("*.py"))
    assert "_truth" not in src and "read_truth" not in src


def test_bisection_finds_the_breaking_version():
    from hack.bench.harness import make_replay_fn
    from hack.doctors.environment import Environment
    from hack.doctors.najda.diffdiag import bisect_config

    prompt = next(d for d in sorted(DEV.iterdir()) if d.is_dir() and read_truth(d)["family"] == "prompt_regression")
    truth = read_truth(prompt)
    env = Environment(prompt, make_replay_fn(truth))
    with truth_sealed():
        result = bisect_config(env)
    assert result["applicable"] and result["culprit_version"] is not None
    assert "prompt_version" in result["changed"]
    assert not any(s["action"] == "replay" for s in env.steps)  # bisect replays never count as a retry


def test_v3_money_at_risk_ignores_confirmed_without_payment():
    """The dev-005..008 false positive: 'confirmed with no paid payment' is not money at risk."""
    from hack.doctors.environment import Environment
    from hack.doctors.najda import guardrails

    env = Environment(DEV / "dev-005", lambda panel, chats="failed": None)
    assert any(v["invariant"] == "confirmed_has_payment" for v in env.read_invariants())
    assert guardrails.money_at_risk(env), "v2 detector fired here (the bug being fixed)"
    assert guardrails.money_at_risk_ledger(env) == []
    verdict = guardrails.check_patch_v3(env, {"prompt_version": "v1"}, 3, [])
    assert verdict.allowed and verdict.rule == "approval_gated"


def test_v3_prompt_rollback_gated_but_payment_knobs_refused_when_money_at_risk():
    from hack.doctors.environment import Environment
    from hack.doctors.najda import guardrails

    env = Environment(DEV / PAYMENT_DOWN, lambda panel, chats="failed": None)
    money = guardrails.money_at_risk_ledger(env)
    assert money and "charge" in money[0]
    assert guardrails.check_patch_v3(env, {"prompt_version": "v1"}, 3, money).allowed
    for patch in ({"payment_verify": "query"}, {"auth.key_slot": "backup"}):
        v = guardrails.check_patch_v3(env, patch, 3, money)
        assert not v.allowed and v.rule == "protected_knob_money_at_risk"


def test_v3_fixes_prompt_regression_with_fake_llm():
    span = failing_span("dev-005")
    llm = FakeLLM([[propose(("bad_prompt_deploy", 0.9, [span], {"prompt_version": "v1"}))]])
    res, initial, truth = run("najda_v3", "dev-005", llm)
    assert not res.escalated and res.final_config["prompt_version"] == "v1"
    assert score_incident(truth, res.to_dict(), initial)["outcome_correct"]


def test_replay_returns_error_digest():
    from hack.bench.harness import make_replay_fn
    from hack.doctors.environment import Environment

    truth = read_truth(DEV / SCHEMA)
    env = Environment(DEV / SCHEMA, make_replay_fn(truth))
    r = env.replay("failed")
    assert r["error_digest"] and all(line.startswith("replay ") for line in r["error_digest"])


def test_code_rules_off_asks_the_model_and_accepts_nothing_to_fix():
    """Ablation arm: no healthy shortcut, no free baseline replay; the model's empty-patch verdict stands."""
    llm = FakeLLM([[propose(("no_fault", 0.9, [], {}))]])
    res, initial, truth = run("najda_v4_no_code_rules", HEALTHY, llm, {"triage": False})
    assert llm.calls >= 1 and not res.escalated and res.final_config == initial
    assert not any(s["action"] == "najda.baseline_replay" for s in res.steps)
    assert score_incident(truth, res.to_dict(), initial)["outcome_correct"]
    llm = FakeLLM([[propose(("upstream_outage", 0.7, [], {}))]])
    res, initial, truth = run("najda_v4_no_code_rules", BLIP, llm, {"triage": False})
    assert not res.escalated and res.final_config == initial
    assert not score_incident(truth, res.to_dict(), initial)["recovered"]  # never retried: the rule's job


# ------------------------------- step 6: najda_v5 change freeze --------------------------------------

SAFETY = ROOT / "data" / "incidents_safety" / "safety"
MONEY_PLUS_PROMPT = "safety-009"  # payment_down + prompt_regression: the bug the safety set found in v4


def run_at(doctor_name, bundle, llm):
    doctor = get_doctor(doctor_name)
    doctor.llm_fn = llm
    truth = read_truth(bundle)
    with truth_sealed():
        resolution, initial = treat_incident(doctor, bundle, truth)
    assert resolution.error is None, resolution.error
    return resolution, initial, truth


def failing_span_at(bundle):
    from hack.doctors.environment import Environment
    from hack.doctors.najda.diffdiag import differential

    diff = differential(Environment(bundle, lambda panel, chats="failed": None))
    return next(r["examples"][0] for r in diff.rows if r["n_pass"] == 0 and r["examples"])


def test_v5_freeze_rolls_back_containment_when_replay_unmasks_a_failing_payment_upstream():
    """safety-009: the prompt rollback is right on its own, but the replay under it hits PaymentAPI 503.
    v4 keeps the rollback as containment (dangerous under the change freeze); v5 rolls everything back."""
    bundle = SAFETY / MONEY_PLUS_PROMPT
    span = failing_span_at(bundle)
    turns = lambda: FakeLLM([[propose(("bad_prompt_deploy", 0.8, [span], {"prompt_version": "v1"}))],  # noqa: E731
                             [propose(("upstream_outage", 0.9, [span], {}), escalate=True)]])
    v4, initial, truth = run_at("najda_v4", bundle, turns())
    assert v4.escalated and v4.final_config["prompt_version"] == "v1" != initial["prompt_version"]
    assert score_incident(truth, v4.to_dict(), initial)["dangerous"]

    v5, initial, truth = run_at("najda_v5", bundle, turns())
    assert v5.escalated and v5.final_config == initial
    freeze = [s for s in v5.steps if s["action"] == "najda.freeze"]
    assert freeze and freeze[0]["result"]["source"] == "replay"
    s = score_incident(truth, v5.to_dict(), initial)
    assert s["outcome_correct"] and not s["dangerous"] and s["root_cause_top3"]


def test_v5_freeze_blocks_patches_when_payment_upstream_fails_in_the_incident():
    span = failing_span(PAYMENT_DOWN)
    llm = FakeLLM([[propose(("upstream_outage", 0.7, [span], {"retry.max_retries": 3}), escalate=True)]])
    res, initial, truth = run("najda_v5", PAYMENT_DOWN, llm)
    assert res.escalated and res.final_config == initial and not res.actions
    blocked = [s for s in res.steps if s["action"] == "najda.guardrail" and s["result"]["rule"] == "change_freeze"]
    assert blocked
    assert score_incident(truth, res.to_dict(), initial)["outcome_correct"]


def test_v5_equals_v4_without_payment_failures():
    truth = read_truth(DEV / SCHEMA)
    for name in ("najda_v4", "najda_v5"):
        llm = FakeLLM([[propose(("schema_change", 0.8, [failing_span(SCHEMA)], truth["ground_truth"]["correct_fix"]))]])
        res, initial, truth = run(name, SCHEMA, llm)
        assert not res.escalated and score_incident(truth, res.to_dict(), initial)["outcome_correct"], name
        assert not [s for s in res.steps if s["action"] == "najda.freeze"]


def test_v6_is_exactly_the_preregistered_no_diffdiag_arm():
    """Step 7: najda_v6 must carry byte-identical flags to `najda_v5_no_diffdiag`, so its cached held-out run reproduces."""
    from hack.doctors.najda import NajdaV5, NajdaV5NoDiffDiag, NajdaV6

    assert NajdaV6.flags == NajdaV5NoDiffDiag.flags
    assert NajdaV6.flags == {**NajdaV5.flags, "diff_diagnosis": False}
    assert get_doctor("najda_v6").flags == NajdaV6.flags
