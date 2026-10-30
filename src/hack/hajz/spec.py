"""Hajz as a registered Patient: descriptions, config, money declarations and bench hooks. Plumbing only."""
from __future__ import annotations

from typing import Any

from hack.faults.catalog import merged_truth
from hack.hajz.bot import HajzBot
from hack.hajz.brain import BookingBrain
from hack.hajz.chats import SCRIPTS_BY_ID
from hack.hajz.config import KNOB_DOCS, BookingConfig, validate_patch
from hack.hajz.faults import COMBOS, FAULT_LABELS, FAULTS, apply_faults
from hack.hajz.invariants import booking_completed, check_invariants
from hack.hajz.world import World
from hack.patient.tracing import metrics_from_spans
from hack.patients import Patient, PatientBench, register

DESCRIPTION = ("an AI WhatsApp restaurant reservation bot (Arabic/English, deposits in SAR).\n"
               "The bot calls AvailabilityAPI, BookingAPI, DepositAPI and NotifyAPI through a tool loop: parse request -> check\n"
               "availability -> create booking -> charge deposit -> send confirmation -> reply.")
SHORT_DESCRIPTION = ("an AI WhatsApp restaurant reservation bot (Arabic/English, deposits in SAR).\n"
                     "The bot calls AvailabilityAPI, BookingAPI, DepositAPI and NotifyAPI.")
TRIAGE_DESCRIPTION = ("an AI restaurant reservation bot (AvailabilityAPI, BookingAPI,\n"
                      "DepositAPI, NotifyAPI; Arabic/English chats; SAR deposits)")

API_CONTRACT: dict[str, set[str]] = {  # documented response keys per tool (from the API docs)
    "check_availability": {"slot_time", "available", "tables_left", "cached"},
    "create_booking": {"booking_id", "status", "slot_time", "party_size", "deposit_sar"},
    "get_booking": {"booking_id", "status", "slot_time", "party_size", "deposit_sar"},
    "charge_deposit": {"deposit_id", "booking_id", "status", "amount_sar"},
    "send_confirmation": {"booking_id", "status"},
}
COUNTERS = {"bookings_created": "create_booking", "deposits_paid": "charge_deposit",
            "confirmations_sent": "send_confirmation"}


def ledger_entry(tool: str, result: dict[str, Any]) -> tuple[str, str, float] | None:
    """A booking's deposit is the expected amount; a paid deposit is the charged amount."""
    if tool in ("create_booking", "get_booking") and "booking_id" in result and "deposit_sar" in result:
        return "expected", str(result["booking_id"]), float(result["deposit_sar"])
    if tool == "charge_deposit" and result.get("status") == "paid" and "amount_sar" in result:
        return "charged", str(result.get("booking_id")), float(result["amount_sar"])
    return None


def committed_amount(tool: str, result: dict[str, Any]) -> float | None:
    if tool == "create_booking":
        return float(result.get("deposit_sar") or 0.0)
    return None


def make_brain(kind: str) -> Any:
    if kind != "scripted":
        raise NotImplementedError("Hajz has a scripted brain only (the LLM patient brain is order-bot specific)")
    return BookingBrain()


@register("hajz")
def hajz_patient() -> tuple[Patient, PatientBench]:
    patient = Patient(
        name="hajz",
        description=DESCRIPTION, short_description=SHORT_DESCRIPTION, triage_description=TRIAGE_DESCRIPTION,
        knob_docs=dict(KNOB_DOCS), record_noun="bookings",
        config_cls=BookingConfig, validate_patch=validate_patch,
        protected_knobs=("prompt_version", "auth.key_slot"), protected_markers=("deposit", "payment"),
        money_knobs=("auth.key_slot",), money_prefixes=("auth.",),
        payment_tools=frozenset({"charge_deposit"}),
        money_invariants=frozenset({"deposit_has_confirmed_booking", "deposit_charged_once"}), money_detail_marker="paid",
        ledger_entry=ledger_entry, committed_amount=committed_amount, api_contract=API_CONTRACT,
    )
    bench = PatientBench(
        name="hajz",
        build_world=lambda seed, incident_id, clock_offset_s=0.0: World.build(seed, incident_id, clock_offset_s),
        apply_faults=apply_faults, make_bot=HajzBot, make_brain=make_brain, scripts=SCRIPTS_BY_ID,
        check_invariants=check_invariants, completed=booking_completed,
        metrics_from_spans=lambda spans, outcomes: metrics_from_spans(spans, outcomes, COUNTERS),
        faults=FAULTS, combos=COMBOS, fault_labels=FAULT_LABELS,
        merged_truth=lambda ids: merged_truth(ids, FAULTS),
    )
    return patient, bench
