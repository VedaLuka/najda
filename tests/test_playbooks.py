"""najda_v4 playbooks: learn only from verified fixes, deterministic tier-1 match, demotion + fallback,
no guardrail bypass, store round trip. Fake LLM, no API key."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hack.bench.harness import make_replay_fn, treat_incident  # noqa: E402
from hack.bench.score import score_incident  # noqa: E402
from hack.bench.seal import truth_sealed  # noqa: E402
from hack.bench.truth import read_truth  # noqa: E402
from hack.doctors import get_doctor  # noqa: E402
from hack.doctors.environment import Environment  # noqa: E402
from hack.doctors.najda import guardrails  # noqa: E402
from hack.doctors.najda.diffdiag import bisect_config  # noqa: E402
from hack.doctors.najda.playbooks import Playbook, PlaybookStore, build_evidence  # noqa: E402
from test_najda import FakeLLM, failing_span, propose  # noqa: E402

DEV = ROOT / "data" / "incidents" / "dev"
SCHEMA_A, SCHEMA_B, PAYMENT_DOWN, BLIP = "dev-001", "dev-002", "dev-029", "dev-038"
SCHEMA_FIX = {"field_mappings.order_id": "id"}


def evidence(incident):
    env = Environment(DEV / incident, make_replay_fn(read_truth(DEV / incident)))
    return build_evidence(env, bisect_config(env), guardrails.money_at_risk_ledger(env))


def treat(doctor, incident, llm):
    doctor.llm_fn = llm
    truth = read_truth(DEV / incident)
    with truth_sealed():
        res, initial = treat_incident(doctor, DEV / incident, truth)
    assert res.error is None, res.error
    return res, score_incident(truth, res.to_dict(), initial)


def events(res):
    return [s["result"]["event"] for s in res.steps if s["action"] == "najda.playbook"]


def test_tier1_signature_is_deterministic_and_structured():
    a, b = evidence(SCHEMA_A), evidence(SCHEMA_A)
    assert a.key == b.key and a.bag == b.bag
    assert all(":" in t and "dev-" not in t for t in a.key)
    assert evidence(SCHEMA_B).key == a.key  # same symptoms, different incident


def test_learns_only_from_a_verified_fix_and_reuses_it_without_llm():
    doctor = get_doctor("najda_v4_nt")
    llm = FakeLLM([[propose(("schema_drift", 0.9, [failing_span(SCHEMA_A)], SCHEMA_FIX))]])
    res1, s1 = treat(doctor, SCHEMA_A, llm)
    assert s1["outcome_correct"] and "learned" in events(res1)
    store = doctor.memory["playbooks"]
    assert len(store.playbooks) == 1 and store.playbooks[0].kind == "fix"
    assert store.playbooks[0].steps == [{"field_mappings.order_id": {"$key_for": "order_id", "tool": "create_order"}}]

    llm2 = FakeLLM([])
    res2, s2 = treat(doctor, SCHEMA_B, llm2)
    assert llm2.calls == 0 and res2.llm_calls == 0
    assert s2["outcome_correct"] and "hit" in events(res2)
    assert res2.final_config["field_mappings"]["order_id"] == "id"
    assert store.playbooks[0].successes == 1


def test_never_learns_from_unverified_escalated_or_transient_outcomes():
    doctor = get_doctor("najda_v4_nt")
    wrong = {"retry.max_retries": 3}
    llm = FakeLLM([[propose(("schema_drift", 0.9, [failing_span(SCHEMA_A)], wrong))],
                   [propose(("schema_drift", 0.5, [failing_span(SCHEMA_A)], wrong))],
                   [propose(("schema_drift", 0.5, [failing_span(SCHEMA_A)], wrong))]])
    res, _ = treat(doctor, SCHEMA_A, llm)
    assert res.escalated and doctor.memory["playbooks"].playbooks == []
    res, _ = treat(doctor, BLIP, FakeLLM([[propose(("transient_upstream_error", 0.8, [], {}))]]))
    assert not res.escalated and doctor.memory["playbooks"].playbooks == []
    # a must-escalate WITHOUT money evidence is never stored as escalate-fast either
    res, _ = treat(doctor, "dev-031", FakeLLM([[propose(("upstream_data_corruption", 0.8, [], {}), escalate=True)]]))
    assert res.escalated and doctor.memory["playbooks"].playbooks == []


def test_failing_playbook_is_rolled_back_demoted_and_falls_back_to_investigation():
    doctor = get_doctor("najda_v4_nt")
    ev = evidence(SCHEMA_A)
    bad = Playbook("pb001", "fix", "schema_drift", list(ev.key), sorted(ev.bag), [{"retry.max_retries": 3}], "t", "x")
    doctor.memory["playbooks"] = PlaybookStore([bad])
    for incident in (SCHEMA_A, SCHEMA_B):
        llm = FakeLLM([[propose(("schema_drift", 0.9, [failing_span(incident)], SCHEMA_FIX))]])
        res, s = treat(doctor, incident, llm)
        assert s["outcome_correct"] and llm.calls == 1 and "false_match" in events(res)
        assert res.final_config["retry"]["max_retries"] != 3
    assert bad.failures == 2 and bad.disabled
    # the wrong playbook is gone but the verified fix was learned as a new one
    store = doctor.memory["playbooks"]
    assert [p.kind for p in store.active()] == ["fix"] and store.active()[0].id != "pb001"
    res, _ = treat(doctor, "dev-004", FakeLLM([]))
    assert "hit" in events(res) and res.llm_calls == 0


def test_playbook_cannot_bypass_guardrails():
    doctor = get_doctor("najda_v4_nt")
    ev = evidence(PAYMENT_DOWN)
    assert ev.money
    bad = Playbook("pb001", "fix", "upstream_outage", list(ev.key), sorted(ev.bag), [{"payment_verify": "query"}], "t", "x")
    doctor.memory["playbooks"] = PlaybookStore([bad])
    res, s = treat(doctor, PAYMENT_DOWN, FakeLLM([[propose(("upstream_outage", 0.9, [], {}), escalate=True)]]))
    assert res.escalated and s["outcome_correct"] and not s["dangerous"]
    assert res.final_config["payment_verify"] == "webhook"
    blocked = [st for st in res.steps if st["action"] == "najda.guardrail" and not st["result"]["allowed"]]
    assert blocked and "false_match" in events(res) and bad.failures == 1


def test_escalate_fast_playbook_needs_money_and_exact_match():
    doctor = get_doctor("najda_v4_nt")
    res, s = treat(doctor, PAYMENT_DOWN, FakeLLM([[propose(("upstream_outage", 0.9, [], {}), escalate=True)]]))
    assert res.escalated and s["outcome_correct"]
    store = doctor.memory["playbooks"]
    assert [p.kind for p in store.playbooks] == ["escalate"]
    llm = FakeLLM([])
    res2, s2 = treat(doctor, "dev-030", llm)
    assert llm.calls == 0 and res2.escalated and s2["outcome_correct"] and "hit_escalate" in events(res2)
    assert s2["root_cause_top1"] and res2.root_causes[0].label == "upstream_outage"
    assert store.match(evidence(SCHEMA_A), {}, 0.0) is None  # no money at risk -> never matches


def test_store_round_trip(tmp_path):
    doctor = get_doctor("najda_v4_nt")
    treat(doctor, SCHEMA_A, FakeLLM([[propose(("schema_drift", 0.9, [failing_span(SCHEMA_A)], SCHEMA_FIX))]]))
    path = tmp_path / "playbooks.json"
    doctor.save_memory(path)
    other = get_doctor("najda_v4_nt")
    other.load_memory(path)
    assert [p.to_dict() for p in other.memory["playbooks"].playbooks] == [p.to_dict() for p in doctor.memory["playbooks"].playbooks]
    assert json.loads(path.read_text())["playbooks"][0]["source_incident"] == SCHEMA_A


def test_partial_hit_on_a_second_fault_is_not_a_false_match_and_the_rest_is_investigated():
    """A playbook that fixes one of two faults is kept as an improvement, not demoted; the investigation
    continues with the replay digest and the second fix completes the recovery."""
    doctor = get_doctor("najda_v4_nt")
    ev = evidence("dev-009")
    retry = Playbook("pb001", "fix", "rate_limiting", list(ev.key), sorted(ev.bag),
                     [{"retry.max_retries": 3, "retry.backoff_s": 1.0}], "t", "dev-009")
    doctor.memory["playbooks"] = PlaybookStore([retry])
    llm = FakeLLM([[propose(("schema_change", 0.9, [failing_span("dev-025")], SCHEMA_FIX))]])
    res, s = treat(doctor, "dev-025", llm)
    assert "partial" in events(res) and "false_match" not in events(res)
    assert retry.failures == 0 and retry.uses == 1 and not retry.disabled
    assert s["outcome_correct"] and llm.calls == 1  # the investigation ran once, after the partial hit
