"""Business invariants: the ground on which recovery is proven. Checked against the service
ledgers and the chat results, never against what the bot *said*."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from hack.patient.bot import ChatResult
from hack.patient.menu import price_of
from hack.patient.tracing import HARD_MAX_TURNS
from hack.patient.world import World


@dataclass(frozen=True)
class Violation:
    invariant: str
    chat_id: str | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_invariants(world: World, chats: list[ChatResult]) -> list[Violation]:
    orders, payments = world.order_api.orders, world.payment_api.payments
    chat_of_order = {c.order_id: c.chat_id for c in chats if c.order_id}
    paid_by_order = {p.order_id: p for p in payments.values() if p.status == "paid"}
    out: list[Violation] = []

    for o in orders.values():
        chat = chat_of_order.get(o.order_id)
        if o.status == "confirmed":
            pay = paid_by_order.get(o.order_id)
            if pay is None:
                out.append(Violation("confirmed_has_payment", chat, f"{o.order_id} confirmed with no paid payment"))
            elif abs(pay.amount_sar - o.total_sar) > 0.005:
                out.append(Violation("confirmed_has_payment", chat, f"{o.order_id} paid {pay.amount_sar} != total {o.total_sar}"))
            expected = price_of(o.items)
            if abs(o.total_sar - expected) > 0.005:
                out.append(Violation("total_matches_menu", chat, f"{o.order_id} total {o.total_sar} SAR, menu says {expected}"))

    for p in paid_by_order.values():
        order = orders.get(p.order_id)
        if order is None or order.status != "confirmed":
            out.append(Violation("payment_has_confirmed_order", chat_of_order.get(p.order_id),
                                 f"{p.payment_id} paid {p.amount_sar} SAR for {p.order_id} which is not confirmed"))

    for c in chats:
        order = orders.get(c.order_id) if c.order_id else None
        if c.outcome == "confirmed":
            if order is None or order.status != "confirmed":
                out.append(Violation("reply_matches_ledger", c.chat_id, "bot told the customer the order is confirmed but the ledger disagrees"))
            elif c.expected_items is not None and order.items != c.expected_items:
                out.append(Violation("qty_matches_request", c.chat_id, f"customer asked {c.expected_items}, order has {order.items}"))
        if c.outcome == "declined" and order is not None and order.status == "confirmed":
            out.append(Violation("reply_matches_ledger", c.chat_id, "customer declined but an order was confirmed"))
        if c.turns > HARD_MAX_TURNS:
            out.append(Violation("turns_under_cap", c.chat_id, f"{c.turns} turns > hard cap {HARD_MAX_TURNS}"))
        if c.error:
            out.append(Violation("no_unhandled_error", c.chat_id, c.error))
    return out


def order_completed(world: World, chat: ChatResult) -> bool:
    """Did the customer get what they asked for (or a clean decline)?"""
    order = world.order_api.orders.get(chat.order_id) if chat.order_id else None
    if chat.expected_items is None:
        return chat.outcome == "declined" and (order is None or order.status != "confirmed")
    if chat.outcome != "confirmed" or order is None or order.status != "confirmed":
        return False
    paid = any(p.order_id == order.order_id and p.status == "paid" for p in world.payment_api.payments.values())
    return paid and order.items == chat.expected_items and abs(order.total_sar - price_of(order.items)) < 0.005
