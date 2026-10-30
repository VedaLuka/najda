"""The order bot as a registered Patient (plumbing only: descriptions, config, money declarations, bench hooks)."""
from __future__ import annotations

from typing import Any

from hack.bench.chats import SCRIPTS_BY_ID
from hack.faults.catalog import COMBOS, FAULT_LABELS, FAULTS, apply_faults, merged_truth
from hack.patient.bot import OrderBot
from hack.patient.brains import LLMBrain, ScriptedBrain
from hack.patient.config import KNOB_DOCS, BotConfig, validate_patch
from hack.patient.invariants import check_invariants, order_completed
from hack.patient.tracing import metrics_from_spans
from hack.patient.world import World
from hack.patients import Patient, PatientBench, register

DESCRIPTION = ("an AI WhatsApp ordering bot (Arabic/English, prices in SAR).\n"
               "The bot calls OrderAPI, StockAPI and PaymentAPI through a tool loop: parse order -> check stock -> create order\n"
               "-> charge -> confirm -> reply.")
SHORT_DESCRIPTION = ("an AI WhatsApp ordering bot (Arabic/English, prices in SAR).\n"
                     "The bot calls OrderAPI, StockAPI and PaymentAPI.")
TRIAGE_DESCRIPTION = "an AI ordering bot (OrderAPI, StockAPI,\nPaymentAPI; Arabic/English chats; SAR prices)"

API_CONTRACT: dict[str, set[str]] = {  # documented response keys per tool (from the API docs)
    "check_stock": {"sku", "qty_available", "price", "cached"},
    "create_order": {"order_id", "status", "total_sar"},
    "get_order": {"order_id", "status", "total_sar"},
    "confirm_order": {"order_id", "status"},
    "charge": {"payment_id", "order_id", "status", "amount_sar"},
    "get_payment": {"payment_id", "order_id", "status", "amount_sar"},
    "webhook_status": {"order_id", "status"},
}


def ledger_entry(tool: str, result: dict[str, Any]) -> tuple[str, str, float] | None:
    """An order's total is the expected amount; a paid charge is the charged amount."""
    if tool in ("create_order", "get_order") and "order_id" in result and "total_sar" in result:
        return "expected", str(result["order_id"]), float(result["total_sar"])
    if tool == "charge" and result.get("status") == "paid" and "amount_sar" in result:
        return "charged", str(result.get("order_id")), float(result["amount_sar"])
    return None


def committed_amount(tool: str, result: dict[str, Any]) -> float | None:
    if tool == "create_order":
        return float(result.get("total_sar") or 0.0)
    return None


def make_brain(kind: str) -> Any:
    return LLMBrain() if kind == "llm" else ScriptedBrain()


@register("order")
def order_patient() -> tuple[Patient, PatientBench]:
    patient = Patient(
        name="order",
        description=DESCRIPTION, short_description=SHORT_DESCRIPTION, triage_description=TRIAGE_DESCRIPTION,
        knob_docs=dict(KNOB_DOCS), record_noun="orders",
        config_cls=BotConfig, validate_patch=validate_patch,
        protected_knobs=("prompt_version", "payment_verify", "auth.key_slot"), protected_markers=("payment",),
        money_knobs=("payment_verify", "auth.key_slot"), money_prefixes=("auth.",),
        payment_tools=frozenset({"charge", "get_payment", "webhook_status"}),
        money_invariants=frozenset({"payment_has_confirmed_order"}), money_detail_marker="paid",
        ledger_entry=ledger_entry, committed_amount=committed_amount, api_contract=API_CONTRACT,
    )
    bench = PatientBench(
        name="order",
        build_world=lambda seed, incident_id, clock_offset_s=0.0: World.build(seed, incident_id, clock_offset_s=clock_offset_s),
        apply_faults=apply_faults, make_bot=OrderBot, make_brain=make_brain, scripts=SCRIPTS_BY_ID,
        check_invariants=check_invariants, completed=order_completed, metrics_from_spans=metrics_from_spans,
        faults=FAULTS, combos=COMBOS, fault_labels=FAULT_LABELS, merged_truth=merged_truth,
    )
    return patient, bench
