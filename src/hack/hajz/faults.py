"""Hajz faults: how to break a Hajz World and what the correct fix is (hidden ground truth).

Some are analogues of the order bot's dev families (field rename, 429s, prompt regression, hallucinated tool,
key rotation); the rest are kinds that appear in no other split: timezone offset, d/m vs m/d dates, Hijri vs
Gregorian, duplicate deposit capture (money at risk), stale availability cache (double bookings).
"""
from __future__ import annotations

import re
from typing import Any, Callable

from hack.faults.catalog import NOISE_LEVELS, Fault, GroundTruth, add_noise
from hack.hajz.services import CAPACITY
from hack.hajz.world import World
from hack.patient.chaos import CallContext
from hack.patient.services import ServiceError

FAULTS: dict[str, Fault] = {}
STALE_SNAPSHOT_TIME = "2025-12-30T22:00:00Z"


def _fault(id: str, family: str, description: str, root_cause: str, fix: dict[str, Any] | None,
           escalate: bool = False, outcome: str = "recover") -> Callable:
    def wrap(apply: Callable[[World], None]) -> Callable[[World], None]:
        FAULTS[id] = Fault(id, family, "transfer", description, apply, GroundTruth(root_cause, fix, escalate, outcome))
        return apply
    return wrap


def _on(service: str, methods: tuple[str, ...] | None = None) -> Callable[[CallContext], bool]:
    return lambda ctx: ctx.service == service and (methods is None or ctx.method in methods)


# ------------------------------ analogues of dev families ------------------------------

@_fault("booking_field_rename", "booking_field_rename",
        "BookingAPI v2 renamed `booking_id` to `id` in every response.",
        "BookingAPI response schema changed: booking_id -> id; bot reads a missing key",
        {"field_mappings.booking_id": "id"})
def booking_field_rename(world: World) -> None:
    match = _on("BookingAPI")

    def rename(ctx: CallContext) -> None:
        if match(ctx) and isinstance(ctx.result, dict) and "booking_id" in ctx.result:
            ctx.result["id"] = ctx.result.pop("booking_id")
    world.chaos.after.append(rename)


@_fault("availability_429", "availability_429",
        "AvailabilityAPI returns 429 on two out of every three calls.",
        "AvailabilityAPI rate limiting; bot has no retry policy",
        {"retry.max_retries": 3, "retry.backoff_s": 0.5})
def availability_429(world: World) -> None:
    match = _on("AvailabilityAPI")

    def limit(ctx: CallContext) -> None:
        if match(ctx) and ctx.call_index % 3 != 0:
            raise ServiceError(429, "rate limit exceeded, retry-after: 1")
    world.chaos.before.append(limit)


@_fault("prompt_regression", "prompt_regression",
        "A new prompt version (v2_quick) sends the confirmation before charging the deposit.",
        "prompt v2_quick dropped the charge_deposit step; bookings are confirmed with no deposit",
        {"prompt_version": "v1"})
def prompt_regression(world: World) -> None:
    world.panel.apply({"prompt_version": "v2_quick"}, "deploy: faster confirmations (deposit collected at the door)",
                      "dev-team", world.clock.now())


@_fault("hallucinated_tool", "hallucinated_tool",
        "A loyalty prompt (v1_loyalty) tells the bot to call add_loyalty_points, a tool that does not exist.",
        "prompt v1_loyalty references non-existent tool add_loyalty_points",
        {"prompt_version": "v1"})
def hallucinated_tool(world: World) -> None:
    world.panel.apply({"prompt_version": "v1_loyalty"}, "deploy: loyalty points pilot", "marketing", world.clock.now())


@_fault("auth_expired_401", "auth_expired_401",
        "Scheduled key rotation revoked the primary API key; the replacement sits in the backup slot.",
        "primary API key revoked by scheduled rotation; bot still uses the primary key slot",
        {"auth.key_slot": "backup"})
def auth_expired_401(world: World) -> None:
    world.booking_api.tokens = {world.secrets["backup"]}
    world.deposit_api.tokens = {world.secrets["backup"]}
    announced = {"done": False}

    def announce(ctx: CallContext) -> None:
        if not announced["done"]:
            announced["done"] = True
            ctx.logs.append(("WARN", "secrets-manager: scheduled rotation completed for key 'hajz-bot' "
                                     "(slot primary revoked, slot backup active)"))
    world.chaos.before.append(announce)


# ------------------------------ kinds that appear in no other split ---------------------

@_fault("tz_offset", "tz_offset",
        "The scheduling services now store the wall-clock time as UTC, ignoring the offset the bot sends: every "
        "booking lands 3 hours late (20:00 Riyadh is saved as 20:00 UTC = 23:00 Riyadh), with no error.",
        "scheduling services ignore the tz offset and store wall-clock as UTC; bot sends Riyadh local time",
        {"timezone": "UTC"})
def tz_offset(world: World) -> None:
    world.scheduling.honour_tz = False


DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})\b")


@_fault("date_swap", "date_swap",
        "The new WhatsApp booking widget pre-fills dates as m/d; the bot reads them as d/m: bookings land on the "
        "wrong day silently, or fail on an impossible month.",
        "customer messages now carry m/d dates; the bot parses d/m",
        {"date_format": "mdy"})
def date_swap(world: World) -> None:
    world.chaos.message_transforms.append(lambda text: DATE_RE.sub(lambda m: f"{m[2]}/{m[1]}", text))


@_fault("hijri_calendar", "hijri_calendar",
        "The scheduling services switched their date field to the Hijri (Umm al-Qura) calendar; Gregorian dates "
        "from the bot are rejected as out of range.",
        "scheduling services expect Hijri dates; bot sends Gregorian",
        {"calendar": "hijri"})
def hijri_calendar(world: World) -> None:
    world.scheduling.calendar = "hijri"


@_fault("stale_availability", "stale_availability",
        "AvailabilityAPI's cache serves an old snapshot in which every slot is free; full slots get booked twice.",
        "AvailabilityAPI cached reads return a stale snapshot (all slots free); bot does not request fresh reads",
        {"availability_fresh_read": True})
def stale_availability(world: World) -> None:
    match = _on("AvailabilityAPI")

    def stale(ctx: CallContext) -> None:
        if match(ctx) and isinstance(ctx.result, dict) and not ctx.args.get("fresh"):
            ctx.result.update({"available": True, "tables_left": CAPACITY, "cached": True, "as_of": STALE_SNAPSHOT_TIME})
    world.chaos.after.append(stale)


@_fault("duplicate_deposit", "escalate",
        "The deposit gateway retries every capture internally; each charge_deposit creates two paid deposits.",
        "deposit gateway captures every charge twice (missing idempotency); customers double-charged, needs a human",
        None, escalate=True, outcome="unfixable")
def duplicate_deposit(world: World) -> None:
    match = _on("DepositAPI", ("charge_deposit",))

    def twice(ctx: CallContext) -> None:
        if match(ctx) and isinstance(ctx.result, dict):
            world.deposit_api._charge(ctx.args["booking_id"], float(ctx.args["amount_sar"]))  # noqa: SLF001
    world.chaos.after.append(twice)


@_fault("deposit_down", "escalate",
        "The deposit provider is fully down (503 on every charge).",
        "deposit provider outage; nothing in the bot config can fix it",
        None, escalate=True, outcome="contain")
def deposit_down(world: World) -> None:
    match = _on("DepositAPI", ("charge_deposit",))

    def down(ctx: CallContext) -> None:
        if match(ctx):
            raise ServiceError(503, "deposit provider unavailable")
    world.chaos.before.append(down)


@_fault("healthy", "healthy", "No fault. Everything works.", "no fault", {}, outcome="recover")
def healthy(world: World) -> None:
    return None


COMBOS: dict[str, tuple[str, str]] = {
    "combo_tz_429": ("tz_offset", "availability_429"),
    "combo_rename_prompt": ("booking_field_rename", "prompt_regression"),
}

# Acceptable generic root-cause labels per fault (hack.doctors.taxonomy). Read by the scorer only.
FAULT_LABELS: dict[str, set[str]] = {
    "healthy": {"no_fault"},
    "booking_field_rename": {"schema_change"},
    "availability_429": {"rate_limiting"},
    "prompt_regression": {"bad_prompt_deploy"},
    "hallucinated_tool": {"invalid_tool", "bad_prompt_deploy"},
    "auth_expired_401": {"auth_failure"},
    "tz_offset": {"unit_mismatch", "schema_change"},
    "date_swap": {"input_format"},
    "hijri_calendar": {"schema_change", "unit_mismatch"},
    "stale_availability": {"stale_data"},
    "duplicate_deposit": {"data_corruption", "ambiguous_state"},
    "deposit_down": {"upstream_outage"},
}


def apply_faults(world: World, fault_ids: list[str], noisy: bool = False, modifiers: list[str] | None = None,
                 noise_level: str | None = None) -> None:
    """Faults first, then noise (the bench's legacy `noisy` flag or a named level). Hajz has no modifiers."""
    if modifiers:
        raise ValueError(f"Hajz has no modifiers: {modifiers}")
    for fid in fault_ids:
        FAULTS[fid].apply(world)
    if noise_level and noise_level != "none":
        p, n = NOISE_LEVELS[noise_level]
        add_noise(world, p, n)
    elif noisy:
        add_noise(world)
