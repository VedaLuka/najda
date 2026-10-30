"""Four fake services with ledgers. Every call goes through the chaos layer (hack.patient.chaos).

Slot handling is shared through `Scheduling`: both AvailabilityAPI and BookingAPI parse the (date, time, tz)
triple the same way, so a change there moves every stored slot at once.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from hack.hajz.calendar import gregorian_from_hijri, iso_utc, parse_gregorian, slot_utc
from hack.patient.clock import VirtualClock
from hack.patient.services import ServiceError

VALID_TOKENS = {"tok_v1"}
CAPACITY = 3  # tables per slot


@dataclass
class Scheduling:
    """How the scheduling services read an incoming (date, time, tz)."""
    calendar: str = "gregorian"   # "gregorian" | "hijri": calendar of the incoming date field
    honour_tz: bool = True        # False: the wall-clock time is taken as UTC whatever offset is sent

    def parse(self, date_s: str, time_s: str, tz: str) -> datetime:
        try:
            day = gregorian_from_hijri(date_s) if self.calendar == "hijri" else parse_gregorian(date_s)
        except ValueError as e:
            raise ServiceError(400, f"invalid date for calendar {self.calendar}: {e}") from None
        return slot_utc(day, time_s, tz if self.honour_tz else "+00:00")


@dataclass
class Booking:
    booking_id: str
    slot: datetime            # UTC
    party_size: int
    customer: str | None
    deposit_sar: float
    status: str = "held"      # held | confirmed | cancelled
    seq: int = 0


@dataclass
class Deposit:
    deposit_id: str
    booking_id: str
    amount_sar: float
    status: str = "paid"


@dataclass
class BookingAPI:
    clock: VirtualClock
    scheduling: Scheduling
    deposit_per_guest: float
    tokens: set[str] = field(default_factory=lambda: set(VALID_TOKENS))
    bookings: dict[str, Booking] = field(default_factory=dict)
    latency_s: float = 0.15

    def seed(self, slot: datetime, n: int) -> None:
        """Bookings taken over the phone before the incident: they fill a slot without a chat."""
        for _ in range(n):
            self._add(slot, 2, None)

    def _add(self, slot: datetime, party_size: int, customer: str | None) -> Booking:
        b = Booking(f"BK-{len(self.bookings) + 1:04d}", slot, party_size, customer, party_size * self.deposit_per_guest,
                    seq=len(self.bookings) + 1)
        self.bookings[b.booking_id] = b
        return b

    def at(self, slot: datetime) -> list[Booking]:
        return [b for b in self.bookings.values() if b.slot == slot and b.status != "cancelled"]

    def create_booking(self, date: str, time: str, tz: str, party_size: int, customer: str, token: str) -> dict[str, Any]:
        self.clock.sleep(self.latency_s)
        if token not in self.tokens:
            raise ServiceError(401, "token expired")
        b = self._add(self.scheduling.parse(date, time, tz), int(party_size), customer)
        return self._view(b)

    def get_booking(self, booking_id: str) -> dict[str, Any]:
        self.clock.sleep(self.latency_s / 2)
        return self._view(self._get(booking_id))

    def confirm(self, booking_id: str) -> Booking:
        b = self._get(booking_id)
        b.status = "confirmed"
        return b

    def _get(self, booking_id: str) -> Booking:
        if booking_id not in self.bookings:
            raise ServiceError(404, f"unknown booking {booking_id}")
        return self.bookings[booking_id]

    @staticmethod
    def _view(b: Booking) -> dict[str, Any]:
        return {"booking_id": b.booking_id, "status": b.status, "slot_time": iso_utc(b.slot),
                "party_size": b.party_size, "deposit_sar": b.deposit_sar}


@dataclass
class AvailabilityAPI:
    clock: VirtualClock
    scheduling: Scheduling
    booking_api: BookingAPI
    latency_s: float = 0.08

    def check_availability(self, date: str, time: str, tz: str, party_size: int, fresh: bool = False) -> dict[str, Any]:
        self.clock.sleep(self.latency_s)
        slot = self.scheduling.parse(date, time, tz)
        left = CAPACITY - len(self.booking_api.at(slot))
        return {"slot_time": iso_utc(slot), "available": left > 0, "tables_left": max(left, 0), "cached": not fresh}


@dataclass
class DepositAPI:
    clock: VirtualClock
    tokens: set[str] = field(default_factory=lambda: set(VALID_TOKENS))
    deposits: dict[str, Deposit] = field(default_factory=dict)
    latency_s: float = 0.3

    def charge_deposit(self, booking_id: str, amount_sar: float, token: str) -> dict[str, Any]:
        self.clock.sleep(self.latency_s)
        if token not in self.tokens:
            raise ServiceError(401, "token expired")
        d = self._charge(booking_id, float(amount_sar))
        return {"deposit_id": d.deposit_id, "booking_id": booking_id, "status": d.status, "amount_sar": d.amount_sar}

    def _charge(self, booking_id: str, amount_sar: float) -> Deposit:
        d = Deposit(f"DEP-{len(self.deposits) + 1:04d}", booking_id, amount_sar)
        self.deposits[d.deposit_id] = d
        return d

    def paid_for(self, booking_id: str) -> list[Deposit]:
        return [d for d in self.deposits.values() if d.booking_id == booking_id and d.status == "paid"]


@dataclass
class NotifyAPI:
    clock: VirtualClock
    booking_api: BookingAPI
    latency_s: float = 0.05

    def send_confirmation(self, booking_id: str) -> dict[str, Any]:
        self.clock.sleep(self.latency_s)
        b = self.booking_api.confirm(booking_id)
        return {"booking_id": b.booking_id, "status": "sent"}
