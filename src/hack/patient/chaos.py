"""Every service call goes through ChaosLayer.call(). Faults register hooks here.

A hook is a callable taking a CallContext. `before` hooks may raise ServiceError, add latency or
rewrite args; `after` hooks may rewrite the result. Noise hooks emit irrelevant log lines.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable

from hack.patient.clock import VirtualClock


@dataclass
class CallContext:
    service: str
    method: str
    args: dict[str, Any]
    call_index: int           # nth call to this service.method in this world
    result: Any = None
    logs: list[tuple[str, str]] = field(default_factory=list)  # (level, message) emitted by hooks


Hook = Callable[[CallContext], None]


class ChaosLayer:
    def __init__(self, clock: VirtualClock, rng: random.Random) -> None:
        self.clock = clock
        self.rng = rng
        self.before: list[Hook] = []
        self.after: list[Hook] = []
        self.message_transforms: list[Callable[[str], str]] = []
        self.counts: dict[str, int] = {}

    def call(self, service: Any, method: str, **args: Any) -> tuple[Any, list[tuple[str, str]]]:
        key = f"{type(service).__name__}.{method}"
        self.counts[key] = self.counts.get(key, 0) + 1
        ctx = CallContext(type(service).__name__, method, args, self.counts[key])
        for hook in self.before:
            hook(ctx)
        ctx.result = getattr(service, method)(**ctx.args)
        for hook in self.after:
            hook(ctx)
        return ctx.result, ctx.logs

    def transform_message(self, text: str) -> str:
        for fn in self.message_transforms:
            text = fn(text)
        return text
