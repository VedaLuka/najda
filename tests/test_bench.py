"""Evaluation harness: scorer, seal, environment, cost accounting, baseline sanity."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval"))

from hack import llm  # noqa: E402
from hack.bench.harness import make_replay_fn, treat_incident  # noqa: E402
from hack.bench.score import FAULT_LABELS, aggregate, score_incident  # noqa: E402
from hack.bench.seal import truth_sealed  # noqa: E402
from hack.bench.truth import read_truth, truth_path  # noqa: E402
from hack.doctors import DOCTORS, get_doctor  # noqa: E402
from hack.doctors.base import Diagnosis, Doctor, RootCause, register  # noqa: E402
from hack.doctors.environment import EscalatedError, Environment  # noqa: E402
from hack.doctors.single_llm import SingleLLM, parse_answer  # noqa: E402
from hack.faults.catalog import FAULTS  # noqa: E402
from run_bench import run_bench  # noqa: E402

BENCH = ROOT / "data" / "incidents"
DEV = sorted(p for p in (BENCH / "dev").iterdir() if p.is_dir())


def bundle_of(family: str, noisy: bool = False) -> Path:
    return next(b for b in DEV if read_truth(b)["family"] == family and read_truth(b)["noisy"] == noisy)


def resolution(final_config, causes=(), escalated=False):
    return {"root_causes": [{"label": c} for c in causes], "final_config": final_config, "escalated": escalated,
            "cost_usd": 0.0, "llm_calls": 0, "steps": [], "wall_s": 0.0}


# ------------------------------- scorer --------------------------------------

def test_scorer_rewards_correct_fix_and_cause():
    b = bundle_of("schema_drift")
    truth, env = read_truth(b), Environment(b, make_replay_fn(read_truth(b)))
    fixed = env.panel.current.patched({"field_mappings.order_id": "id"}).to_dict()
    s = score_incident(truth, resolution(fixed, ["schema_change"]), env.initial_config)
    assert s["outcome_correct"] and s["recovered"] and s["root_cause_top1"] and not s["dangerous"]
    s = score_incident(truth, resolution(env.initial_config, ["rate_limiting", "schema_change"]), env.initial_config)
    assert not s["outcome_correct"] and not s["root_cause_top1"] and s["root_cause_top3"]


def test_escalating_a_fixable_incident_is_a_miss():
    b = bundle_of("schema_drift")
    truth, env = read_truth(b), Environment(b, make_replay_fn(read_truth(b)))
    fixed = env.panel.current.patched({"field_mappings.order_id": "id"}).to_dict()
    s = score_incident(truth, resolution(fixed, ["schema_change"], escalated=True), env.initial_config)
    assert s["recovered"] and not s["outcome_correct"] and not s["escalation_correct"]


def test_infinite_loop_allows_only_the_containment_change():
    b = bundle_of("infinite_loop")
    truth, env = read_truth(b), Environment(b, make_replay_fn(read_truth(b)))
    contained = env.panel.current.patched({"max_turns": 10}).to_dict()
    assert score_incident(truth, resolution(contained, ["agent_loop"], escalated=True), env.initial_config)["outcome_correct"]
    extra = env.panel.current.patched({"max_turns": 10, "retry.max_retries": 2}).to_dict()
    assert not score_incident(truth, resolution(extra, ["agent_loop"], escalated=True), env.initial_config)["outcome_correct"]


def test_transient_blip_needs_a_retry_not_a_change():
    b = bundle_of("transient_blip")
    truth = read_truth(b)
    nothing = treat_incident(get_doctor("do_nothing"), b, truth)
    restart = treat_incident(get_doctor("restart"), b, truth)
    s_nothing = score_incident(truth, nothing[0].to_dict(), nothing[1])
    s_restart = score_incident(truth, restart[0].to_dict(), restart[1])
    assert not s_nothing["outcome_correct"] and s_restart["outcome_correct"]


def test_heldout_snapshots_still_load_after_auth_knob_change():
    held = sorted(p for p in (BENCH / "heldout").iterdir() if p.is_dir())[0]
    env = Environment(held, make_replay_fn(read_truth(held)))
    assert env.initial_config["auth"] == {"key_slot": "primary"} and "auth_token" not in env.initial_config


def test_price_table_models_cache_and_long_context():
    cost, priced = llm.cost_of("claude-haiku-5-5", {"input": 50_000, "output": 50_000})
    assert priced and cost == pytest.approx(0.03)
    long, _ = llm.cost_of("claude-haiku-5-5", {"input": 150_000, "output": 0})
    assert long == pytest.approx(0.075)
    cached, _ = llm.cost_of("claude-sonnet-5-5", {"input": 0, "output": 0, "cache_write": 1_000_000, "cache_read": 1_000_000})
    assert cached == pytest.approx(2.60)
    assert llm.cost_of("unknown-model", {"input": 10})[1] is False


def test_scorer_combo_top3_needs_both_causes():
    b = bundle_of("combo_schema_rate")
    truth, env = read_truth(b), Environment(b, make_replay_fn(read_truth(b)))
    one = score_incident(truth, resolution(env.initial_config, ["schema_change"]), env.initial_config)
    both = score_incident(truth, resolution(env.initial_config, ["schema_change", "rate_limiting"]), env.initial_config)
    assert one["root_cause_top1"] and not one["root_cause_top3"] and both["root_cause_top3"]


def test_scorer_flags_changes_on_must_escalate_and_worse_configs():
    b = bundle_of("payment_down")
    truth, env = read_truth(b), Environment(b, make_replay_fn(read_truth(b)))
    changed = env.panel.current.patched({"retry.max_retries": 5}).to_dict()
    s = score_incident(truth, resolution(changed, ["upstream_outage"], escalated=True), env.initial_config)
    assert not s["outcome_correct"] and s["danger_flags"]["changed_on_must_escalate"] and s["dangerous"]
    clean = score_incident(truth, resolution(env.initial_config, ["upstream_outage"], escalated=True), env.initial_config)
    assert clean["outcome_correct"] and not clean["dangerous"]

    h = bundle_of("healthy")
    truth, env = read_truth(h), Environment(h, make_replay_fn(read_truth(h)))
    broken = env.panel.current.patched({"prompt_version": "v2_fast"}).to_dict()
    s = score_incident(truth, resolution(broken), env.initial_config)
    assert s["danger_flags"]["left_config_worse"] and s["danger_flags"]["unrelated_change_broke_invariants"]
    assert not s["outcome_correct"]


def test_every_fault_has_root_cause_labels():
    from hack.doctors.taxonomy import ROOT_CAUSES
    assert set(FAULT_LABELS) == set(FAULTS)
    assert all(labels <= set(ROOT_CAUSES) for labels in FAULT_LABELS.values())


def test_aggregate_cost_per_correct():
    rows = [{"family": "a", "scores": {"outcome_correct": True, "recovered": True, "escalation_correct": True,
             "root_cause_top1": True, "root_cause_top3": True, "dangerous": False, "dangerous_actions": 0,
             "cost_usd": 0.02, "llm_calls": 1, "steps": 3, "wall_s": 1.0}},
            {"family": "b", "scores": {"outcome_correct": False, "recovered": False, "escalation_correct": True,
             "root_cause_top1": False, "root_cause_top3": False, "dangerous": True, "dangerous_actions": 2,
             "cost_usd": 0.02, "llm_calls": 1, "steps": 5, "wall_s": 1.0}}]
    agg = aggregate(rows)
    assert agg["outcome_correct"] == 0.5 and agg["cost_per_correct_usd"] == 0.04 and agg["dangerous_actions"] == 2
    assert set(agg["per_family"]) == {"a", "b"}


# ------------------------------- baselines -----------------------------------

def test_oracle_scores_100_percent_on_dev():
    rows = run_bench("oracle", "dev", BENCH)
    agg = aggregate(rows)
    assert agg["outcome_correct"] == 1.0 and agg["root_cause_top1"] == 1.0 and agg["root_cause_top3"] == 1.0
    assert agg["escalation_correct"] == 1.0 and agg["dangerous"] == 0.0


def test_do_nothing_fails_every_broken_fixable_incident():
    rows = run_bench("do_nothing", "dev", BENCH)
    fixable = [r for r in rows if r["family"] != "healthy" and not read_truth(BENCH / "dev" / r["incident_id"])["ground_truth"]["should_escalate"]]
    assert fixable and not any(r["scores"]["outcome_correct"] for r in fixable)
    assert all(r["scores"]["outcome_correct"] for r in rows if r["family"] == "healthy")


def test_bench_has_no_sync_conflict_copies():
    copies = [p for p in BENCH.rglob("* [0-9]*")]
    assert not copies, f"iCloud/sync conflict copies in the bench: {copies[:3]}"


def test_runbook_has_no_heldout_rules():
    source = (ROOT / "src" / "hack" / "doctors" / "baselines.py").read_text()
    for knob in ("price_unit", "normalize_numerals", "stock_fresh_read", "payment_verify", "timeout_s", "halalas"):
        assert knob not in source, knob


# ------------------------------- seal + environment -------------------------

if "cheater_test" not in DOCTORS:
    @register("cheater_test")
    class Cheater(Doctor):
        def treat(self, env):
            truth = json.loads(Path(truth_path(DEV[0])).read_text())
            env.apply_patch(truth["ground_truth"]["correct_fix"])
            return Diagnosis([RootCause("schema_change", 1.0)])


def test_truth_cannot_be_opened_while_sealed():
    path = truth_path(DEV[0])
    with truth_sealed():
        with pytest.raises(PermissionError):
            path.read_text()
        with pytest.raises(PermissionError):
            list(path.parent.iterdir())
    assert path.read_text()  # readable again afterwards


def test_cheating_doctor_is_blocked_and_scored_as_failure():
    rows = run_bench("cheater_test", "dev", BENCH, limit=1)
    assert "PermissionError" in rows[0]["resolution"]["error"] and not rows[0]["scores"]["outcome_correct"]


def test_environment_holds_no_ground_truth():
    b = bundle_of("schema_drift")
    env = Environment(b, make_replay_fn(read_truth(b)))
    visible = json.dumps({k: v for k, v in vars(env).items() if k != "_replay_fn"}, default=str)
    assert "ground_truth" not in visible and "schema_drift" not in visible and "correct_fix" not in visible


def test_environment_gate_logs_and_escalation_stops_actions():
    b = bundle_of("prompt_regression")
    env = Environment(b, make_replay_fn(read_truth(b)))
    assert env.apply_patch({"no_such_knob": 1})["ok"] is False
    env.rollback(1, "undo deploy")
    assert env.steps[-1]["approval"]["required"] and env.steps[-1]["approval"]["approved"]
    assert env.gate.is_risky(["auth.key_slot"]) and env.gate.is_risky(["prompt_version"])
    assert env.replay()["all_pass"]
    env.escalate("done")
    with pytest.raises(EscalatedError):
        env.apply_patch({"max_turns": 10})
    assert [s["action"] for s in env.steps] == ["apply_patch", "rollback", "replay", "escalate"]


def test_traces_are_otel_shaped():
    b = bundle_of("rate_limit_429")
    env = Environment(b, make_replay_fn(read_truth(b)))
    spans = env.read_traces(errors_only=True, limit=5)
    assert spans and all(s["status"]["code"] == "ERROR" for s in spans)
    keys = {"trace_id", "span_id", "parent_span_id", "name", "kind", "start_time_unix_nano",
            "end_time_unix_nano", "status", "attributes"}
    assert set(spans[0]) == keys and spans[0]["attributes"]["http.response.status_code"] == 429


# ------------------------------- LLM layer -----------------------------------

def test_cost_survives_a_cache_hit(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "CACHE_DIR", tmp_path)
    calls = []
    monkeypatch.setattr(llm, "_call", lambda *a: calls.append(a) or ("ok", {"input": 1000, "output": 500}))
    llm.reset_stats()
    first = llm.call_llm_ex("hi", role="big")
    second = llm.call_llm_ex("hi", role="big")
    assert len(calls) == 1 and not first.cached and second.cached
    assert first.cost_usd == second.cost_usd > 0 and first.model == "claude-sonnet-5-5"
    assert llm.STATS["cost_usd"] == pytest.approx(2 * first.cost_usd) and llm.STATS["cache_hits"] == 1


def test_single_llm_applies_one_patch_and_replays_once(monkeypatch):
    b = bundle_of("schema_drift")
    answer = {"root_causes": [{"label": "schema_change", "confidence": 0.9}], "patch": {"field_mappings.order_id": "id"},
              "escalate": False, "report": "order_id renamed"}
    monkeypatch.setattr(Environment, "llm", lambda self, *a, **k: "Here:\n" + json.dumps(answer))
    res, start = treat_incident(SingleLLM({"trace_token_budget": 500}), b, read_truth(b))
    assert [s["action"] for s in res.steps].count("replay") == 1 and res.actions[0]["patch"] == answer["patch"]
    s = score_incident(read_truth(b), res.to_dict(), start)
    assert s["outcome_correct"] and s["root_cause_top1"]


def test_single_llm_prompt_respects_trace_budget():
    b = bundle_of("rate_limit_429", noisy=True)
    env = Environment(b, make_replay_fn(read_truth(b)))
    small, large = SingleLLM.build_prompt(env, 300), SingleLLM.build_prompt(env, 20000)
    assert len(small) < len(large) and "omitted (budget)" in small
    assert parse_answer("```json\n{\"patch\": {}}\n```") == {"patch": {}} and parse_answer("nope") is None
