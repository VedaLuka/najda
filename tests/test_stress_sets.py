"""Step 5 stress sets: modifiers, conditions, plans and the frozen manifests."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hack.bench.incidents import (  # noqa: E402
    DEV_FAULTS, HELDOUT_FAULTS, IncidentSpec, bench_plan, drop_spans, pick_chats,
                                  robustness_plan, run_incident, safety_plan)
from hack.faults.catalog import COMBOS, DECOY_LINES, MODIFIERS  # noqa: E402


def test_drop_spans_is_seeded_and_near_fraction():
    spans = [{"i": i} for i in range(1000)]
    a, b = drop_spans(spans, 0.3, 7), drop_spans(spans, 0.3, 7)
    assert a == b
    assert 620 <= len(a) <= 780
    assert drop_spans(spans, 0.0, 7) == spans


def test_pick_chats_language_filter():
    assert all(c.startswith("ar_") for c in pick_chats(4101, language="ar"))
    assert all(c.startswith("en_") for c in pick_chats(4101, language="en"))
    assert len(pick_chats(4019, 2, 2)) == 2


def test_plans_use_dev_families_and_fresh_seeds():
    bench_seeds = {s.seed for s in bench_plan()}
    dev_ok = set(DEV_FAULTS) | {"payment_down", "stock_corrupt"}
    for plan in (safety_plan(), robustness_plan()):
        ids = [s.incident_id for s in plan]
        assert len(ids) == len(set(ids))
        for s in plan:
            assert s.seed not in bench_seeds
            faults = {f for fid in s.fault_ids for f in COMBOS.get(fid, (fid,))}
            assert faults <= dev_ok and not (faults & set(HELDOUT_FAULTS))
            assert set(s.modifiers) <= set(MODIFIERS)


def test_decoy_history_adds_an_ops_deploy_without_changing_the_fault():
    plain = run_incident(IncidentSpec("t", "dev", 3010, ["payment_down"], chat_ids=pick_chats(3010)))
    decoy = run_incident(IncidentSpec("t", "dev", 3010, ["payment_down"], chat_ids=pick_chats(3010),
                                      modifiers=["decoy_history"]))
    hist = decoy.world.panel.history
    assert hist[-1].actor == "ops-team" and hist[-1].patch == {"timeout_s": 4.0}
    assert {c: v["pass"] for c, v in plain.chat_verdicts().items()} == \
           {c: v["pass"] for c, v in decoy.chat_verdicts().items()}


def test_decoy_payment_logs_appear_in_traces():
    run = run_incident(IncidentSpec("t", "dev", 3001, ["schema_drift"], chat_ids=pick_chats(3001),
                                    modifiers=["decoy_payment_logs"]))
    messages = [s.args.get("message", "") for s in run.world.tracer.spans if s.kind == "log"]
    assert any(m in DECOY_LINES for m in messages)


def test_noise_levels_scale_log_volume():
    def n_logs(cond):
        run = run_incident(IncidentSpec("t", "dev", 4001, ["schema_drift"], chat_ids=pick_chats(4001), conditions=cond))
        return sum(1 for s in run.world.tracer.spans if s.kind == "log")
    assert n_logs({}) < n_logs({"noise": "low"}) < n_logs({"noise": "high"})


def test_frozen_sets_match_their_manifests():
    for name in ("safety", "robust"):
        if not (ROOT / "data" / f"incidents_{name}" / "MANIFEST.sha256").exists():
            continue
        r = subprocess.run([sys.executable, "scripts/make_stress_sets.py", "--verify", "--set", name], cwd=ROOT,
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
