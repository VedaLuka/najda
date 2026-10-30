"""Every fault must break something, and every ground-truth fix must restore the bot."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hack.bench.incidents import IncidentSpec, pick_chats, run_incident  # noqa: E402
from hack.faults.catalog import COMBOS, FAULTS, merged_truth  # noqa: E402
from hack.patient.tracing import HARD_MAX_TURNS  # noqa: E402

CASES = [[f] for f in FAULTS if f != "healthy"] + [[c] for c in COMBOS]


def _spec(fault_ids, seed=7):
    return IncidentSpec("test", "dev", seed, fault_ids, False, pick_chats(seed, 6, 6))


@pytest.mark.parametrize("fault_ids", CASES, ids=lambda f: "+".join(f))
def test_fault_breaks_something(fault_ids):
    run = run_incident(_spec(fault_ids))
    verdicts = run.chat_verdicts()
    assert any(not v["pass"] for v in verdicts.values()), "fault had no visible effect"


@pytest.mark.parametrize("fault_ids", CASES, ids=lambda f: "+".join(f))
def test_ground_truth_fix_restores(fault_ids):
    from hack.bench.incidents import resolve_faults

    truth = merged_truth(resolve_faults(fault_ids))
    if truth.expected_outcome == "unfixable":
        assert truth.should_escalate and truth.correct_fix is None
        return
    run = run_incident(_spec(fault_ids), extra_patch=truth.correct_fix or {}, later=True)
    verdicts = run.chat_verdicts()
    assert all(v["invariants_ok"] for v in verdicts.values()), run.violations
    if truth.expected_outcome == "recover":
        assert all(v["pass"] for v in verdicts.values()), verdicts
    else:
        assert truth.should_escalate
        assert max(v["turns"] for v in verdicts.values()) <= HARD_MAX_TURNS


def test_infinite_loop_exceeds_hard_cap_before_fix():
    run = run_incident(_spec(["infinite_loop"]))
    assert max(r.turns for r in run.results) > HARD_MAX_TURNS
    assert {v.invariant for v in run.violations} == {"turns_under_cap"}


def test_transient_blip_clears_on_its_own_and_needs_only_a_retry():
    spec = _spec(["transient_blip"])
    during = run_incident(spec).chat_verdicts()
    later = run_incident(spec, later=True).chat_verdicts()
    assert 0 < sum(not v["pass"] for v in during.values()) < len(during)
    assert all(v["pass"] for v in later.values())
    assert FAULTS["transient_blip"].truth.requires_retry and FAULTS["transient_blip"].truth.correct_fix == {}


def test_auth_fix_is_a_key_slot_switch():
    assert FAULTS["auth_expired_401"].truth.correct_fix == {"auth.key_slot": "backup"}
    run = run_incident(_spec(["auth_expired_401"]))
    logs = " ".join(s.args.get("message", "") for s in run.world.tracer.spans if s.kind == "log")
    assert "tok_v2" not in logs and "slot backup" in logs


def test_noisy_logs_do_not_change_outcomes():
    quiet = run_incident(_spec(["schema_drift"]))
    noisy = run_incident(IncidentSpec("t", "dev", 7, ["schema_drift"], True, pick_chats(7, 6, 6)))
    assert quiet.chat_verdicts() == noisy.chat_verdicts()
    assert sum(s.kind == "log" and s.level == "WARN" for s in noisy.world.tracer.spans) > \
        sum(s.kind == "log" and s.level == "WARN" for s in quiet.world.tracer.spans)
