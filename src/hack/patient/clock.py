"""Virtual time. Services add latency, the bot backs off and times out, all without sleeping."""
from __future__ import annotations


INCIDENT_START = 1_767_225_600.0  # 2026-01-01T00:00:00Z: every incident starts here
REPLAY_OFFSET_S = 3600.0          # replays run an hour later (transient faults have cleared)


class VirtualClock:
    def __init__(self, start: float = INCIDENT_START) -> None:
        self.t = start

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += max(0.0, seconds)
