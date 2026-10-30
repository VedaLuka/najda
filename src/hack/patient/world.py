"""A World is one self-contained run: clock, services, chaos layer, control panel, tracer."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from hack.patient.chaos import ChaosLayer
from hack.patient.clock import INCIDENT_START, VirtualClock
from hack.patient.config import BotConfig, ControlPanel
from hack.patient.services import OrderAPI, PaymentAPI, StockAPI
from hack.patient.tracing import Tracer


@dataclass
class World:
    seed: int
    clock: VirtualClock
    rng: random.Random
    chaos: ChaosLayer
    stock_api: StockAPI
    order_api: OrderAPI
    payment_api: PaymentAPI
    panel: ControlPanel
    tracer: Tracer
    secrets: dict[str, str] = field(default_factory=lambda: {"primary": "tok_v1", "backup": "tok_v2"})

    @classmethod
    def build(cls, seed: int = 0, incident_id: str = "adhoc", config: BotConfig | None = None,
              panel: ControlPanel | None = None, clock_offset_s: float = 0.0) -> "World":
        clock = VirtualClock(INCIDENT_START + clock_offset_s)
        rng = random.Random(seed)
        stock = StockAPI(clock)
        return cls(seed, clock, rng, ChaosLayer(clock, rng), stock, OrderAPI(clock, stock),
                   PaymentAPI(clock), panel or ControlPanel(config, clock.now()), Tracer(clock, incident_id))

    @property
    def api_key(self) -> str:
        return self.secrets[self.config.auth.key_slot]

    @property
    def config(self) -> BotConfig:
        return self.panel.current
