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
    run = run_incident(_spec(fault_ids), extra_patch=truth.correct_fix or {})
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


def test_noisy_logs_do_not_change_outcomes():
    quiet = run_incident(_spec(["schema_drift"]))
    noisy = run_incident(IncidentSpec("t", "dev", 7, ["schema_drift"], True, pick_chats(7, 6, 6)))
    assert quiet.chat_verdicts() == noisy.chat_verdicts()
    assert sum(s.kind == "log" and s.level == "WARN" for s in noisy.world.tracer.spans) > \
        sum(s.kind == "log" and s.level == "WARN" for s in quiet.world.tracer.spans)
