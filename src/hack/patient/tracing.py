"""Structured traces: one JSON line per span. Najda sees these (and the metrics derived from them)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hack.patient.clock import VirtualClock

HARD_MAX_TURNS = 12
RESULT_MAX_CHARS = 400


@dataclass
class Span:
    incident_id: str
    chat_id: str
    span_id: str
    parent_id: str | None
    kind: str                      # tool | llm | reply | log | guard | customer
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    error: str | None = None
    status_code: int | None = None
    t_start: float = 0.0
    t_end: float = 0.0
    latency_ms: float = 0.0
    tokens: int = 0
    level: str = "INFO"


class Tracer:
    def __init__(self, clock: VirtualClock, incident_id: str = "adhoc") -> None:
        self.clock = clock
        self.incident_id = incident_id
        self.spans: list[Span] = []
        self._n = 0

    def start(self, chat_id: str, kind: str, name: str, args: dict[str, Any] | None = None,
              parent_id: str | None = None) -> Span:
        self._n += 1
        span = Span(self.incident_id, chat_id, f"s{self._n:05d}", parent_id, kind, name, args or {},
                    t_start=self.clock.now())
        self.spans.append(span)
        return span

    def end(self, span: Span, result: Any = None, error: str | None = None,
            status_code: int | None = None, tokens: int = 0, level: str = "INFO") -> Span:
        span.t_end = self.clock.now()
        span.latency_ms = round((span.t_end - span.t_start) * 1000, 1)
        span.result = _truncate(result)
        span.error, span.status_code, span.tokens, span.level = error, status_code, tokens, level
        if error and level == "INFO":
            span.level = "ERROR"
        return span

    def log(self, chat_id: str, message: str, level: str = "WARN", parent_id: str | None = None) -> Span:
        span = self.start(chat_id, "log", "log", {"message": message}, parent_id)
        return self.end(span, level=level)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for s in self.spans:
                f.write(json.dumps(asdict(s), ensure_ascii=False, default=str) + "\n")


def _truncate(result: Any) -> Any:
    text = json.dumps(result, ensure_ascii=False, default=str)
    return result if len(text) <= RESULT_MAX_CHARS else text[:RESULT_MAX_CHARS] + "…"


def read_spans(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def metrics_from_spans(spans: list[dict[str, Any]], chat_outcomes: dict[str, str]) -> dict[str, Any]:
    """Simple incident metrics computed only from traces and the bot's declared chat outcomes."""
    chats = sorted({s["chat_id"] for s in spans})
    tool_spans = [s for s in spans if s["kind"] == "tool"]
    per_chat: dict[str, dict[str, Any]] = {}
    for c in chats:
        mine = [s for s in spans if s["chat_id"] == c]
        actions = [s for s in mine if s["kind"] in ("tool", "reply")]
        per_chat[c] = {
            "outcome": chat_outcomes.get(c, "unknown"),
            "turns": len(actions),
            "tool_calls": sum(1 for s in mine if s["kind"] == "tool"),
            "errors": sum(1 for s in mine if s["error"]),
            "latency_ms": round(sum(s["latency_ms"] for s in actions), 1),
            "tokens": sum(s["tokens"] for s in mine),
        }
    latencies = sorted(s["latency_ms"] for s in tool_spans)
    n_tools = len(tool_spans)
    return {
        "chats": len(chats),
        "tool_calls": n_tools,
        "error_rate": round(sum(1 for s in tool_spans if s["error"]) / n_tools, 3) if n_tools else 0.0,
        "mean_tool_latency_ms": round(sum(latencies) / n_tools, 1) if n_tools else 0.0,
        "p95_tool_latency_ms": latencies[int(0.95 * (n_tools - 1))] if n_tools else 0.0,
        "orders_created": sum(1 for s in tool_spans if s["name"] == "create_order" and not s["error"]),
        "orders_paid": sum(1 for s in tool_spans if s["name"] == "charge" and not s["error"]),
        "orders_confirmed": sum(1 for s in tool_spans if s["name"] == "confirm_order" and not s["error"]),
        "chats_confirmed": sum(1 for o in chat_outcomes.values() if o == "confirmed"),
        "chats_failed": sum(1 for o in chat_outcomes.values() if o == "failed"),
        "mean_turns": round(sum(p["turns"] for p in per_chat.values()) / len(chats), 2) if chats else 0.0,
        "loop_chats": sum(1 for p in per_chat.values() if p["turns"] >= HARD_MAX_TURNS),
        "tokens": sum(s["tokens"] for s in spans),
        "warn_logs": sum(1 for s in spans if s["kind"] == "log" and s["level"] == "WARN"),
        "per_chat": per_chat,
    }
