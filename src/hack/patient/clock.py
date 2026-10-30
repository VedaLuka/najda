"""Virtual time. Services add latency, the bot backs off and times out, all without sleeping."""
from __future__ import annotations


class VirtualClock:
    def __init__(self, start: float = 1_767_225_600.0) -> None:  # 2026-01-01T00:00:00Z
        self.t = start

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += max(0.0, seconds)
