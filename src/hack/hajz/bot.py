"""The reservation bot: the same tool-calling loop shape as the order bot, over Hajz's tools and config."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hack.hajz.brain import BookingBrain, BookingState
from hack.hajz.calendar import BookingRequest
from hack.hajz.world import World
from hack.patient.brains import Reply, Tool
from hack.patient.services import ServiceError

LOGICAL_KEYS = ("booking_id", "status", "available", "tables_left", "slot_time", "deposit_sar", "deposit_id", "deposit_status")


@dataclass
class BookingScript:
    id: str
    messages: list[str]
    request: BookingRequest           # what the customer asks for (Riyadh local time)
    wants: bool = True                # False: the customer cancels at the confirmation step
    lang: str = "ar"

    @property
    def expected_outcome(self) -> str:
        """'confirmed' when the customer wants the table and the slot has room, else 'declined'
        (the customer cancelled, or the slot was already full before any chat: see world.FULL_SLOTS)."""
        from hack.hajz.world import FULL_SLOTS

        full = (self.request.day, self.request.time_s) in FULL_SLOTS
        return "confirmed" if self.wants and not full else "declined"


@dataclass
class BookingChatResult:
    chat_id: str
    outcome: str                       # confirmed | declined | failed
    transcript: list[dict[str, str]]
    booking_id: str | None = None
    deposit_id: str | None = None
    turns: int = 0
    error: str | None = None
    request: BookingRequest | None = None
    expected_outcome: str = "confirmed"
    customer_messages: list[str] = field(default_factory=list)


class ToolRouter:
    def __init__(self, world: World) -> None:
        self.world = world

    def execute(self, chat_id: str, tool: Tool) -> dict[str, Any]:
        cfg = self.world.config
        span = self.world.tracer.start(chat_id, "tool", tool.name, tool.args)
        if tool.name not in cfg.allowed_tools or tool.name not in self._dispatch_table():
            self.world.tracer.end(span, error=f"unknown or disallowed tool: {tool.name}", status_code=400)
            return {"tool": tool.name, "args": tool.args, "ok": False, "result": None,
                    "error": f"unknown tool {tool.name}", "status": 400}
        raw, error, status = self._call_with_retries(tool)
        for level, message in self._drain_logs():
            self.world.tracer.log(chat_id, message, level, parent_id=span.span_id)
        result = self._normalize(raw) if error is None else None
        self.world.tracer.end(span, result=raw, error=error, status_code=status)
        return {"tool": tool.name, "args": tool.args, "ok": error is None, "result": result,
                "error": error, "status": status}

    def _call_with_retries(self, tool: Tool) -> tuple[Any, str | None, int | None]:
        cfg = self.world.config
        self._logs: list[tuple[str, str]] = []
        for attempt in range(cfg.retry.max_retries + 1):
            t0 = self.world.clock.now()
            try:
                raw, logs = self._dispatch_table()[tool.name](**tool.args)
                self._logs += logs
            except ServiceError as e:
                self._logs.append(("ERROR", f"{tool.name} attempt {attempt + 1}: {e}"))
                if e.status in cfg.retry.retry_on and attempt < cfg.retry.max_retries:
                    self.world.clock.sleep(cfg.retry.backoff_s * (2 ** attempt))
                    continue
                return None, f"{e.status} {e.message}", e.status
            except TypeError as e:
                return None, f"bad arguments: {e}", 400
            except Exception as e:  # noqa: BLE001 - a service bug surfaces as a 500, not a bot crash
                return None, f"internal error: {type(e).__name__}: {e}", 500
            if self.world.clock.now() - t0 > cfg.timeout_s:
                return None, f"timeout after {cfg.timeout_s}s", 504
            return raw, None, 200
        return None, "retries exhausted", 429

    def _drain_logs(self) -> list[tuple[str, str]]:
        logs, self._logs = self._logs, []
        return logs

    def _normalize(self, raw: Any) -> dict[str, Any]:
        cfg = self.world.config
        if not isinstance(raw, dict):
            return {"raw": raw}
        return {k: raw.get(cfg.field_mappings.get(k, k)) for k in LOGICAL_KEYS}

    def _dispatch_table(self) -> dict[str, Any]:
        w, cfg = self.world, self.world.config
        call = w.chaos.call
        return {
            "check_availability": lambda date, time, tz, party_size: call(
                w.availability_api, "check_availability", date=date, time=time, tz=tz, party_size=party_size,
                fresh=cfg.availability_fresh_read),
            "create_booking": lambda date, time, tz, party_size, customer: call(
                w.booking_api, "create_booking", date=date, time=time, tz=tz, party_size=party_size, customer=customer,
                token=w.api_key),
            "get_booking": lambda booking_id: call(w.booking_api, "get_booking", booking_id=booking_id),
            "charge_deposit": lambda booking_id, amount_sar: call(
                w.deposit_api, "charge_deposit", booking_id=booking_id, amount_sar=amount_sar, token=w.api_key),
            "send_confirmation": lambda booking_id: call(w.notify_api, "send_confirmation", booking_id=booking_id),
        }


class HajzBot:
    def __init__(self, world: World, brain: BookingBrain) -> None:
        self.world = world
        self.brain = brain
        self.router = ToolRouter(world)

    def run_chat(self, script: BookingScript) -> BookingChatResult:
        cfg = self.world.config
        tracer = self.world.tracer
        state = BookingState(script.id, script.lang)
        result = BookingChatResult(script.id, "failed", [], request=script.request, expected_outcome=script.expected_outcome)
        self.brain.start_chat(cfg)
        try:
            for raw_msg in script.messages:
                msg = self.world.chaos.transform_message(raw_msg)
                result.customer_messages.append(msg)
                result.transcript.append({"role": "customer", "text": msg})
                tracer.end(tracer.start(script.id, "customer", "message", {"text": msg}))
                obs: dict[str, Any] = {"customer": msg}
                while True:
                    if result.turns >= cfg.max_turns:
                        tracer.end(tracer.start(script.id, "guard", "max_turns", {"max_turns": cfg.max_turns}),
                                   error="max_turns reached", status_code=None, level="WARN")
                        text = ("نعتذر، ما قدرنا نكمل حجزك الحين. حاول بعد شوي." if state.lang == "ar"
                                else "Sorry, we couldn't complete your booking right now. Please try again later.")
                        self._reply(result, Reply(text, "failed"))
                        return self._finish(result, state)
                    llm_span = tracer.start(script.id, "llm", "decide")
                    action, tokens = self.brain.decide(state, obs)
                    tracer.end(llm_span, result=_action_repr(action), tokens=tokens)
                    result.turns += 1
                    if isinstance(action, Reply):
                        self._reply(result, action)
                        if action.outcome != "pending":
                            return self._finish(result, state)
                        break
                    obs = self.router.execute(script.id, action)
                    self.world.clock.sleep(0.02)
            if result.outcome not in ("confirmed", "declined", "failed"):
                result.outcome = "failed"
        except Exception as e:  # noqa: BLE001 - an unhandled error is itself a signal we record
            result.error = f"{type(e).__name__}: {e}"
            tracer.end(tracer.start(script.id, "guard", "unhandled_exception"), error=result.error)
        return self._finish(result, state)

    def _reply(self, result: BookingChatResult, reply: Reply) -> None:
        span = self.world.tracer.start(result.chat_id, "reply", reply.outcome, {"text": reply.text})
        self.world.tracer.end(span)
        result.transcript.append({"role": "bot", "text": reply.text})
        result.outcome = reply.outcome

    @staticmethod
    def _finish(result: BookingChatResult, state: BookingState) -> BookingChatResult:
        result.booking_id, result.deposit_id = state.booking_id, state.deposit_id
        if result.outcome == "pending":
            result.outcome = "failed"
        return result


def _action_repr(action: Tool | Reply) -> dict[str, Any]:
    if isinstance(action, Tool):
        return {"tool": action.name, "args": action.args}
    return {"reply": action.text, "outcome": action.outcome}
