"""Bundles are self-contained, the truth lives elsewhere, and replay is deterministic."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hack.bench.incidents import (IncidentSpec, bench_plan, load_bundle, pick_chats, resolve_faults,  # noqa: E402
                                  run_incident, save_bundle)
from hack.bench.replay import replay  # noqa: E402
from hack.bench.truth import read_truth, truth_path  # noqa: E402
from hack.faults.catalog import FAULTS  # noqa: E402

BUNDLE_FILES = {"traces.jsonl", "metrics.json", "config.json", "chats.json", "invariants.json"}


def _bundle(tmp_path, fault="schema_drift", seed=3):
    spec = IncidentSpec("dev-001", "dev", seed, [fault], False, pick_chats(seed, 5, 5))
    return save_bundle(run_incident(spec), tmp_path)


def test_bundle_round_trip_and_truth_is_separate(tmp_path):
    bundle = _bundle(tmp_path)
    assert {p.name for p in bundle.iterdir()} == BUNDLE_FILES
    assert not truth_path(bundle).is_relative_to(bundle) and truth_path(bundle).exists()
    text = "\n".join(p.read_text(encoding="utf-8") for p in bundle.iterdir())
    assert "schema_drift" not in text and "ground_truth" not in text
    loaded = load_bundle(bundle)
    assert loaded["metrics"]["chats"] == 5 and len(loaded["chats"]) == 5 and loaded["traces"]
    assert "expected_items" not in json.dumps(loaded["chats"])


def test_replay_without_patch_reproduces_failures(tmp_path):
    bundle = _bundle(tmp_path)
    truth = read_truth(bundle)
    res = replay(bundle, {}, chats="all")
    assert sorted(c for c, v in res.per_chat.items() if not v["pass"]) == truth["failed_chats"]
    assert res.per_chat == truth["chat_verdicts"]


def test_replay_with_correct_fix_passes_and_wrong_fix_fails(tmp_path):
    bundle = _bundle(tmp_path)
    assert replay(bundle, FAULTS["schema_drift"].truth.correct_fix).all_pass
    assert not replay(bundle, {"timeout_s": 30}).all_pass


def test_bench_plan_splits_families_and_is_seeded():
    specs = bench_plan()
    fam = {s: {FAULTS[f].family for sp in specs if sp.split == s for f in resolve_faults(sp.fault_ids)}
           for s in ("dev", "heldout")}
    assert fam["dev"] & fam["heldout"] == {"healthy", "escalate"}  # only these two are shared by design
    assert len([s for s in specs if s.split == "dev"]) >= 30 and len([s for s in specs if s.split == "heldout"]) >= 20
    assert [s.seed for s in specs] == [s.seed for s in bench_plan()]
    assert all(5 <= len(s.chat_ids) <= 10 for s in specs)
