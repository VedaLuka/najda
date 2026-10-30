"""Hajz, the unseen patient: parsing, calendar, invariants, every fault breaks and its fix repairs, replay via the
registry, the bundle shape matches the order bot's, and the frozen transfer set matches its manifest."""
from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hack.bench.incidents import IncidentSpec, load_bundle, resolve_faults, run_incident, save_bundle  # noqa: E402
from hack.bench.truth import read_truth  # noqa: E402
from hack.doctors.environment import Environment  # noqa: E402
from hack.doctors.najda import prompts  # noqa: E402
from hack.faults.catalog import merged_truth  # noqa: E402
from hack.hajz.bench import pick_chats, transfer_plan  # noqa: E402
from hack.hajz.brain import parse_request  # noqa: E402
from hack.hajz.calendar import gregorian_from_hijri, hijri_from_gregorian, slot_utc  # noqa: E402
from hack.hajz.chats import CHAT_SCRIPTS, FULL_SLOT_CHATS  # noqa: E402
from hack.hajz.config import BookingConfig, validate_patch  # noqa: E402
from hack.hajz.faults import COMBOS, FAULT_LABELS, FAULTS  # noqa: E402
from hack.patients import get_bench, get_patient  # noqa: E402

ALL = [s.id for s in CHAT_SCRIPTS]
TRANSFER = ROOT / "data" / "incidents_transfer"


def passes(run) -> int:
    return sum(v["pass"] for v in run.chat_verdicts().values())


def test_parse_request_reads_dialect_english_and_date_format():
    r = parse_request("ابغى احجز طاولة لـ 4 أشخاص يوم 15/1 الساعة 8 بالليل", "dmy")
    assert (r.day, r.hour, r.minute, r.party) == (date(2026, 1, 15), 20, 0, 4)
    r = parse_request("Can I book for 4 people on 20/1 at 7:30", "dmy")
    assert (r.day, r.hour, r.minute, r.party) == (date(2026, 1, 20), 19, 30, 4)
    assert parse_request("table for 2 on 1/15 at 8pm", "dmy") is None  # month 15
    assert parse_request("table for 2 on 1/15 at 8pm", "mdy").day == date(2026, 1, 15)


def test_hijri_table_round_trips_and_slot_utc():
    for g in (date(2026, 1, 3), date(2026, 1, 15), date(2026, 1, 30)):
        assert gregorian_from_hijri(hijri_from_gregorian(g)) == g
    assert slot_utc(date(2026, 1, 15), "20:00", "+03:00").hour == 17
    assert slot_utc(date(2026, 1, 15), "20:00", "+00:00").hour == 20


def test_config_validate_and_knob_docs_describe_no_failures():
    cfg = BookingConfig()
    assert validate_patch(cfg, {"timezone": "UTC", "field_mappings.booking_id": "id"}) is None
    assert validate_patch(cfg, {"no_such": 1})
    docs = " ".join(get_patient("hajz").knob_docs.values()).lower()
    for word in ("fault", "bug", "broken", "incident", "wrong", "fix", "stale", "twice", "regression"):
        assert word not in docs, word


def test_healthy_world_passes_every_chat():
    run = run_incident(IncidentSpec("t", "transfer", 1, ["healthy"], chat_ids=ALL, patient="hajz"))
    assert passes(run) == len(ALL) and not run.violations


def test_every_fault_breaks_and_its_fix_repairs():
    for fid, f in FAULTS.items():
        if fid == "healthy":
            continue
        spec = IncidentSpec("t", "transfer", 7, [fid], chat_ids=ALL, patient="hajz")
        assert passes(run_incident(spec)) < len(ALL), fid
        if f.truth.correct_fix:
            fixed = run_incident(spec, extra_patch=f.truth.correct_fix, later=True)
            assert passes(fixed) == len(ALL) and not fixed.violations, fid
    for cid in COMBOS:
        spec = IncidentSpec("t", "transfer", 7, [cid], chat_ids=ALL, patient="hajz")
        fix = merged_truth(resolve_faults([cid], "hajz"), FAULTS).correct_fix
        assert passes(run_incident(spec)) < len(ALL)
        assert passes(run_incident(spec, extra_patch=fix, later=True)) == len(ALL)


def test_silent_faults_violate_the_right_invariants():
    def violations(fid):
        return {v.invariant for v in run_incident(IncidentSpec("t", "transfer", 3, [fid], chat_ids=ALL, patient="hajz")).violations}
    assert "booking_time_matches_request" in violations("tz_offset")
    assert "no_double_booking" in violations("stale_availability")
    assert "deposit_charged_once" in violations("duplicate_deposit")
    assert "confirmed_has_deposit" in violations("prompt_regression")


def test_fault_labels_cover_every_fault_and_use_the_generic_taxonomy():
    from hack.doctors.taxonomy import ROOT_CAUSES

    assert set(FAULT_LABELS) == set(FAULTS)
    assert all(labels <= set(ROOT_CAUSES) for labels in FAULT_LABELS.values())


def test_plan_is_seeded_and_every_sample_has_a_full_slot_request():
    specs = transfer_plan()
    assert len({s.incident_id for s in specs}) == len(specs) >= 20 and all(s.patient == "hajz" for s in specs)
    assert [s.chat_ids for s in specs] == [s.chat_ids for s in transfer_plan()]
    for s in specs:
        assert set(s.chat_ids) & set(FULL_SLOT_CHATS)
    assert pick_chats(5001) == pick_chats(5001)


def test_bundle_round_trip_replay_and_prompt_through_registry(tmp_path):
    spec = transfer_plan()[0]
    run = run_incident(spec)
    bundle = save_bundle(run, tmp_path)
    truth = read_truth(bundle)
    assert truth["patient"] == "hajz" and truth["failed_chats"]
    # every chat the bench marks failed is visible to the doctor as a failed outcome or an invariant violation
    env_failed = set(Environment(bundle, lambda panel, chats="failed": None, patient="hajz").failed_chat_ids())
    assert set(truth["failed_chats"]) <= env_failed
    b = load_bundle(bundle)
    assert {s["kind"] for s in b["traces"]} <= {"tool", "llm", "reply", "customer", "log", "guard"}
    assert set(b["metrics"]) >= {"chats", "error_rate", "chats_failed", "loop_chats", "bookings_created"}
    env = Environment(bundle, lambda panel, chats="failed": None, patient="hajz")
    assert env.panel.current.timezone == "Asia/Riyadh"
    system = prompts.system_for(env.patient)
    assert "reservation" in system and "timezone" in system and "OrderAPI" not in system
    for word in ("tz_offset", "date_swap", "hijri_calendar", "stale_availability", "duplicate_deposit", "deposit_down"):
        assert word not in system, word


def test_frozen_transfer_set_matches_manifest():
    if not (TRANSFER / "MANIFEST.sha256").exists():
        return  # not built yet
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "make_transfer_set.py"), "--verify"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert get_bench("hajz").faults  # registry resolves the bench half for the generator


def test_najda_v5_runs_on_hajz_unchanged(tmp_path):
    """End to end on a fresh (unfrozen) Hajz incident with the fake LLM: the same loop that treats the order bot
    verifies a timezone fix by replay, and freezes + escalates when the deposit upstream is down."""
    from hack.bench.harness import treat_incident
    from hack.bench.score import score_incident
    from hack.bench.seal import truth_sealed
    from hack.doctors import get_doctor
    from hack.doctors.najda.diffdiag import differential
    from test_najda import FakeLLM, propose

    def incident(fault, seed):
        spec = IncidentSpec(f"tmp-{fault}", "transfer", seed, [fault], chat_ids=pick_chats(seed), patient="hajz")
        bundle = save_bundle(run_incident(spec), tmp_path)
        return bundle, read_truth(bundle)

    def span_of(bundle):
        diff = differential(Environment(bundle, lambda panel, chats="failed": None, patient="hajz"))
        return next(r["examples"][0] for r in diff.rows if r["n_pass"] == 0 and r["examples"])

    bundle, truth = incident("tz_offset", 9001)
    doctor = get_doctor("najda_v5")
    doctor.llm_fn = FakeLLM([[propose(("stale_data", 0.7, [span_of(bundle)], {"availability_fresh_read": True}),
                                      ("unit_mismatch", 0.6, [span_of(bundle)], {"timezone": "UTC"}))]])
    with truth_sealed():
        res, initial = treat_incident(doctor, bundle, truth)
    assert res.error is None, res.error
    s = score_incident(truth, res.to_dict(), initial)
    assert s["outcome_correct"] and not res.escalated and res.final_config["timezone"] == "UTC"
    assert res.final_config["availability_fresh_read"] is False  # wrong patch rolled back

    bundle, truth = incident("deposit_down", 9002)
    doctor = get_doctor("najda_v5")
    doctor.llm_fn = FakeLLM([[propose(("upstream_outage", 0.9, [span_of(bundle)], {"retry.max_retries": 2}), escalate=True)]])
    with truth_sealed():
        res, initial = treat_incident(doctor, bundle, truth)
    assert res.error is None, res.error
    assert res.escalated and res.final_config == initial
    assert any(st["action"] == "najda.freeze" for st in res.steps)
    assert score_incident(truth, res.to_dict(), initial)["outcome_correct"]


def test_every_bench_failure_is_visible_to_the_doctor():
    """No silent bench failures: a chat the truth marks failed shows a failed outcome or an invariant violation."""
    for spec in transfer_plan():
        run = run_incident(spec)
        bad = {v.chat_id for v in run.violations}
        for chat, verdict in run.chat_verdicts().items():
            if not verdict["pass"]:
                outcome = next(r.outcome for r in run.results if r.chat_id == chat)
                assert outcome == "failed" or chat in bad, (spec.incident_id, chat)
