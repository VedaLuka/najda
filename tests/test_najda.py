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

    env = Environment(DEV / incident, lambda panel, chats="failed": None)
    failing = set(env.failed_chat_ids())
    spans = env.read_traces(kind="tool", errors_only=True, limit=None) or env.read_traces(kind="tool", limit=None)
    return next(s["span_id"] for s in spans if s["attributes"]["chat.id"] in failing)


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
