"""A World is one self-contained run: clock, services, chaos layer, control panel, tracer."""
from __future__ import annotations

import random
from dataclasses import dataclass

from hack.patient.chaos import ChaosLayer
from hack.patient.clock import VirtualClock
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

    @classmethod
    def build(cls, seed: int = 0, incident_id: str = "adhoc", config: BotConfig | None = None,
              panel: ControlPanel | None = None) -> "World":
        clock = VirtualClock()
        rng = random.Random(seed)
        stock = StockAPI(clock)
        return cls(seed, clock, rng, ChaosLayer(clock, rng), stock, OrderAPI(clock, stock),
                   PaymentAPI(clock), panel or ControlPanel(config, clock.now()), Tracer(clock, incident_id))

    @property
    def config(self) -> BotConfig:
        return self.panel.current
