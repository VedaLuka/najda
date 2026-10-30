"""Hajz business invariants, checked against the service ledgers and the chat results, never against what the
bot said: no double booking, deposit charged once and matching the party size, confirmed booking has a paid
deposit, paid deposit has a confirmed booking, booking time matches the request, turn cap, no unhandled error."""
from __future__ import annotations

from hack.hajz.bot import BookingChatResult
from hack.hajz.config import DEPOSIT_PER_GUEST_SAR
from hack.hajz.calendar import to_riyadh
from hack.hajz.services import CAPACITY
from hack.hajz.world import World
from hack.patient.invariants import Violation
from hack.patient.tracing import HARD_MAX_TURNS


def check_invariants(world: World, chats: list[BookingChatResult]) -> list[Violation]:
    bookings, deposit_api = world.booking_api.bookings, world.deposit_api
    chat_of = {c.booking_id: c.chat_id for c in chats if c.booking_id}
    out: list[Violation] = []

    by_slot: dict[str, list] = {}
    for b in bookings.values():
        if b.status != "cancelled":
            by_slot.setdefault(b.slot.isoformat(), []).append(b)
    for slot, bs in by_slot.items():
        for b in sorted(bs, key=lambda x: x.seq)[CAPACITY:]:
            out.append(Violation("no_double_booking", chat_of.get(b.booking_id),
                                 f"{b.booking_id} is booking {len(bs)} of {CAPACITY} tables at {to_riyadh(b.slot)} Riyadh"))

    for b in bookings.values():
        chat = chat_of.get(b.booking_id)
        paid = deposit_api.paid_for(b.booking_id)
        if len(paid) > 1:
            out.append(Violation("deposit_charged_once", chat, f"{b.booking_id} charged {len(paid)} times "
                                                                f"({', '.join(d.deposit_id for d in paid)})"))
        for d in paid:
            if abs(d.amount_sar - b.party_size * DEPOSIT_PER_GUEST_SAR) > 0.005:
                out.append(Violation("deposit_matches_party", chat, f"{d.deposit_id} paid {d.amount_sar} SAR for "
                                                                      f"{b.party_size} guests (expected {b.party_size * DEPOSIT_PER_GUEST_SAR})"))
            if b.status != "confirmed":
                out.append(Violation("deposit_has_confirmed_booking", chat, f"{d.deposit_id} paid {d.amount_sar} SAR for "
                                                                              f"{b.booking_id} which is not confirmed"))
        if b.status == "confirmed" and not paid:
            out.append(Violation("confirmed_has_deposit", chat, f"{b.booking_id} confirmed with no paid deposit"))

    for c in chats:
        b = bookings.get(c.booking_id) if c.booking_id else None
        if c.expected is not None and b is not None:
            if b.slot != c.expected.utc:
                out.append(Violation("booking_time_matches_request", c.chat_id,
                                     f"customer asked {c.expected.day.isoformat()} {c.expected.time_s} Riyadh, "
                                     f"{b.booking_id} is at {to_riyadh(b.slot)} Riyadh"))
            if b.party_size != c.expected.party:
                out.append(Violation("booking_time_matches_request", c.chat_id,
                                     f"customer asked for {c.expected.party} guests, {b.booking_id} has {b.party_size}"))
        if c.outcome == "confirmed" and (b is None or b.status != "confirmed"):
            out.append(Violation("reply_matches_ledger", c.chat_id, "bot told the customer the booking is confirmed but the ledger disagrees"))
        if c.outcome == "declined" and b is not None and b.status == "confirmed":
            out.append(Violation("reply_matches_ledger", c.chat_id, "customer was turned down or declined but a booking was confirmed"))
        if c.turns > HARD_MAX_TURNS:
            out.append(Violation("turns_under_cap", c.chat_id, f"{c.turns} turns > hard cap {HARD_MAX_TURNS}"))
        if c.error:
            out.append(Violation("no_unhandled_error", c.chat_id, c.error))
    return out


def booking_completed(world: World, chat: BookingChatResult) -> bool:
    """Did the customer get the table they asked for (or a clean no)?"""
    b = world.booking_api.bookings.get(chat.booking_id) if chat.booking_id else None
    if chat.expected is None:
        return chat.outcome == "declined" and (b is None or b.status != "confirmed")
    if chat.outcome != "confirmed" or b is None or b.status != "confirmed":
        return False
    paid = world.deposit_api.paid_for(b.booking_id)
    return (len(paid) == 1 and abs(paid[0].amount_sar - b.party_size * DEPOSIT_PER_GUEST_SAR) < 0.005
            and b.slot == chat.expected.utc and b.party_size == chat.expected.party)
