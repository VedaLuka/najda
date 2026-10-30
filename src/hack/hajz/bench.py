"""The transfer split plan: ~22 Hajz incidents, seeded, frozen once (scripts/make_transfer_set.py)."""
from __future__ import annotations

import random

from hack.bench.incidents import IncidentSpec
from hack.hajz.chats import CHAT_SCRIPTS, FULL_SLOT_CHATS

TRANSFER_SEED_BASE = 5000


def pick_chats(seed: int, n_min: int = 5, n_max: int = 8) -> list[str]:
    """Seeded sample that always holds at least one full-slot request and one bookable request."""
    rng = random.Random(f"hajz-chats-{seed}")
    pool = [s.id for s in CHAT_SCRIPTS]
    bookable = [s.id for s in CHAT_SCRIPTS if s.expected is not None]
    chosen = {rng.choice(FULL_SLOT_CHATS), rng.choice(bookable)}
    n = rng.randint(n_min, n_max)
    rest = [c for c in pool if c not in chosen]
    chosen.update(rng.sample(rest, n - len(chosen)))
    return sorted(chosen)


def transfer_plan() -> list[IncidentSpec]:
    plan: list[tuple[list[str], bool]] = (
        [(["tz_offset"], False)] * 2 + [(["date_swap"], False)] * 2 + [(["hijri_calendar"], False)] * 2
        + [(["stale_availability"], False)] * 2 + [(["duplicate_deposit"], False)] * 2 + [(["deposit_down"], False)]
        + [(["booking_field_rename"], False)] * 2 + [(["availability_429"], False)] + [(["prompt_regression"], False)]
        + [(["hallucinated_tool"], False)] + [(["auth_expired_401"], False)]
        + [(["combo_tz_429"], False), (["combo_rename_prompt"], False)]
        + [(["healthy"], False)]
        + [(["tz_offset"], True), (["stale_availability"], True)]
    )
    specs = []
    for k, (faults, noisy) in enumerate(plan, 1):
        seed = TRANSFER_SEED_BASE + k
        specs.append(IncidentSpec(f"transfer-{k:03d}", "transfer", seed, faults, noisy, pick_chats(seed), patient="hajz"))
    return specs
