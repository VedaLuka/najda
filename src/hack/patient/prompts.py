"""Prompt registry. `steps` is the tool plan: the scripted brain executes it literally and the LLM
brain is told to follow it, so both brains share one source of truth per prompt version."""
from __future__ import annotations

from dataclasses import dataclass

BASE_RULES = (
    "You are the order assistant for 'مطعم الديرة' on WhatsApp. Customers write in Arabic "
    "(often Saudi dialect) or English; reply in the customer's language, briefly and politely. "
    "Prices are in SAR. Work step by step using tools. Respond ONLY with one JSON object per turn: "
    '{"tool": "<name>", "args": {...}} to call a tool, or {"reply": "<text>", "outcome": '
    '"confirmed|declined|failed|pending"} to answer the customer.'
)


@dataclass(frozen=True)
class Prompt:
    version: str
    system_text: str
    steps: tuple[str, ...]


PROMPTS: dict[str, Prompt] = {}


def _register(p: Prompt) -> Prompt:
    PROMPTS[p.version] = p
    return p


V1_STEPS = ("parse", "check_stock", "quote", "create_order", "charge", "confirm_order", "reply")

_register(Prompt("v1", BASE_RULES + (
    " Steps: 1) parse items and quantities; 2) check_stock for each item; 3) quote the total and "
    "ask the customer to confirm; 4) after the customer confirms: create_order; 5) charge the "
    "order; 6) confirm_order only after the payment is paid; 7) reply with the order id."
), V1_STEPS))

_register(Prompt("v2_fast", BASE_RULES + (
    " Steps: 1) parse items and quantities; 2) check_stock for each item; 3) quote the total and "
    "ask the customer to confirm; 4) after the customer confirms: create_order; 5) confirm_order "
    "immediately so the kitchen starts (payment is collected on delivery); 6) reply with the order id."
), ("parse", "check_stock", "quote", "create_order", "confirm_order", "reply")))

_register(Prompt("v1_promo", BASE_RULES + (
    " Steps: 1) parse items and quantities; 2) check_stock for each item; 3) quote the total and "
    "ask the customer to confirm; 4) after the customer confirms: create_order; 5) apply_promo "
    "with code RAMADAN10; 6) charge the order; 7) confirm_order; 8) reply with the order id."
), ("parse", "check_stock", "quote", "create_order", "apply_promo", "charge", "confirm_order", "reply")))
