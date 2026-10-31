"""Step 7 confirmation sets: fresh seeds, same families as the frozen held-out / transfer splits."""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hack.bench.incidents import HELDOUT_FAULTS, bench_plan, heldout_confirm_plan, robustness_plan, safety_plan  # noqa: E402
from hack.hajz.bench import transfer_confirm_plan, transfer_plan  # noqa: E402


def test_confirm_seeds_are_new_everywhere():
    used = {s.seed for s in bench_plan()} | {s.seed for s in safety_plan()} | {s.seed for s in robustness_plan()}
    used |= {s.seed for s in transfer_plan()}
    fresh = [s.seed for s in heldout_confirm_plan()] + [s.seed for s in transfer_confirm_plan()]
    assert len(set(fresh)) == len(fresh) and not (set(fresh) & used)


def test_heldout_confirm_mirrors_heldout_composition():
    frozen = Counter((tuple(s.fault_ids), s.noisy) for s in bench_plan() if s.split == "heldout")
    confirm = Counter((tuple(s.fault_ids), s.noisy) for s in heldout_confirm_plan())
    assert confirm == frozen and sum(confirm.values()) == 25
    assert {s.family for s in heldout_confirm_plan()} >= set(HELDOUT_FAULTS)
    # new seeds give new chat samples: the sets do not reuse a single (seed, chats) pair
    assert not ({(s.seed, tuple(s.chat_ids)) for s in heldout_confirm_plan()}
                & {(s.seed, tuple(s.chat_ids)) for s in bench_plan()})


def test_transfer_confirm_uses_only_transfer_families():
    frozen = {tuple(s.fault_ids) for s in transfer_plan()}
    specs = transfer_confirm_plan()
    assert len(specs) == 15 and all(s.patient == "hajz" for s in specs)
    assert {tuple(s.fault_ids) for s in specs} <= frozen
    assert [s.chat_ids for s in specs] == [s.chat_ids for s in transfer_confirm_plan()]
