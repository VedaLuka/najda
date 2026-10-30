"""A Hajz World: clock, four services, chaos layer, control panel, tracer, plus the bookings already on the books."""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date

from hack.hajz.calendar import RIYADH_TZ, slot_utc
from hack.hajz.config import DEPOSIT_PER_GUEST_SAR, BookingConfig
from hack.hajz.services import AvailabilityAPI, BookingAPI, DepositAPI, NotifyAPI, Scheduling
from hack.patient.chaos import ChaosLayer
from hack.patient.clock import INCIDENT_START, VirtualClock
from hack.patient.config import ControlPanel
from hack.patient.tracing import Tracer

# Slots already fully booked over the phone before any chat (Riyadh local time). Chats that ask for them
# must be turned down; a bot that books them anyway double-books the table.
FULL_SLOTS = [(date(2026, 1, 15), "20:00"), (date(2026, 1, 22), "21:00"), (date(2026, 1, 9), "19:00")]


@dataclass
class World:
    seed: int
    clock: VirtualClock
    rng: random.Random
    chaos: ChaosLayer
    scheduling: Scheduling
    availability_api: AvailabilityAPI
    booking_api: BookingAPI
    deposit_api: DepositAPI
    notify_api: NotifyAPI
    panel: ControlPanel
    tracer: Tracer
    secrets: dict[str, str] = field(default_factory=lambda: {"primary": "tok_v1", "backup": "tok_v2"})

    @classmethod
    def build(cls, seed: int = 0, incident_id: str = "adhoc", clock_offset_s: float = 0.0) -> "World":
        clock = VirtualClock(INCIDENT_START + clock_offset_s)
        rng = random.Random(seed)
        scheduling = Scheduling()
        booking = BookingAPI(clock, scheduling, DEPOSIT_PER_GUEST_SAR)
        for day, time_s in FULL_SLOTS:
            booking.seed(slot_utc(day, time_s, RIYADH_TZ), 3)
        return cls(seed, clock, rng, ChaosLayer(clock, rng), scheduling, AvailabilityAPI(clock, scheduling, booking),
                   booking, DepositAPI(clock), NotifyAPI(clock, booking),
                   ControlPanel(BookingConfig(), clock.now()), Tracer(clock, incident_id))

    @property
    def api_key(self) -> str:
        return self.secrets[self.config.auth.key_slot]

    @property
    def config(self) -> BookingConfig:
        return self.panel.current
