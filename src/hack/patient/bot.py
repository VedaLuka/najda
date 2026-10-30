"""The order bot: a tool-calling loop guarded by the control panel config.

ToolRouter is where config meets the world: allowed_tools, retry/backoff, timeout, field
mappings and price unit are all applied here, so the brains only ever see logical keys.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from hack.patient.brains import Brain, ChatState, Reply, Tool
from hack.patient.services import ServiceError
from hack.patient.world import World

LOGICAL_KEYS = ("order_id", "status", "price", "qty_available", "payment_id", "payment_status")


@dataclass
class ChatScript:
    id: str
    messages: list[str]
    expected_items: dict[str, int] | None  # None = customer declines, no order expected
    lang: str = "ar"


@dataclass
class ChatResult:
    chat_id: str
    outcome: str                       # confirmed | declined | failed
    transcript: list[dict[str, str]]   # [{"role": customer|bot, "text": ...}]
    order_id: str | None = None
    payment_id: str | None = None
    turns: int = 0
    error: str | None = None
    expected_items: dict[str, int] | None = None
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
        raw, error, status = self._call_with_retries(chat_id, tool, span.span_id)
        for level, message in self._drain_logs():
            self.world.tracer.log(chat_id, message, level, parent_id=span.span_id)
        result = self._normalize(raw) if error is None else None
        self.world.tracer.end(span, result=raw, error=error, status_code=status)
        return {"tool": tool.name, "args": tool.args, "ok": error is None, "result": result,
                "error": error, "status": status}

    def _call_with_retries(self, chat_id: str, tool: Tool, parent: str) -> tuple[Any, str | None, int | None]:
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
        out = {k: raw.get(cfg.field_mappings.get(k, k)) for k in LOGICAL_KEYS}
        if out["price"] is not None and cfg.price_unit == "halalas":
            out["price"] = out["price"] / 100
        return out

    def _dispatch_table(self) -> dict[str, Any]:
        w, cfg = self.world, self.world.config
        call = w.chaos.call
        return {
            "check_stock": lambda sku: call(w.stock_api, "check_stock", sku=sku, fresh=cfg.stock_fresh_read),
            "create_order": lambda items, total_sar: call(w.order_api, "create_order", items=_as_dict(items),
                                                          total_sar=float(total_sar), token=cfg.auth_token),
            "get_order": lambda order_id: call(w.order_api, "get_order", order_id=order_id),
            "confirm_order": lambda order_id: call(w.order_api, "confirm_order", order_id=order_id),
            "charge": lambda order_id, amount_sar: call(w.payment_api, "charge", order_id=order_id,
                                                        amount_sar=amount_sar, token=cfg.auth_token),
            "get_payment": lambda payment_id: call(w.payment_api, "get_payment", payment_id=payment_id),
            "webhook_status": lambda order_id: call(w.payment_api, "webhook_status", order_id=order_id),
        }


class OrderBot:
    def __init__(self, world: World, brain: Brain) -> None:
        self.world = world
        self.brain = brain
        self.router = ToolRouter(world)

    def run_chat(self, script: ChatScript) -> ChatResult:
        cfg = self.world.config
        tracer = self.world.tracer
        state = ChatState(script.id, script.lang)
        result = ChatResult(script.id, "failed", [], expected_items=script.expected_items)
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
                        text = ("نعتذر، ما قدرنا نكمل طلبك الحين. حاول بعد شوي." if state.lang == "ar"
                                else "Sorry, we couldn't complete your order right now. Please try again later.")
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
                    _remember_ids(state, obs)
                    self.world.clock.sleep(0.02)
            if result.outcome not in ("confirmed", "declined", "failed"):
                result.outcome = "failed"
        except Exception as e:  # noqa: BLE001 - an unhandled error is itself a signal we record
            result.error = f"{type(e).__name__}: {e}"
            tracer.end(tracer.start(script.id, "guard", "unhandled_exception"), error=result.error)
        return self._finish(result, state)

    def _reply(self, result: ChatResult, reply: Reply) -> None:
        span = self.world.tracer.start(result.chat_id, "reply", reply.outcome, {"text": reply.text})
        self.world.tracer.end(span)
        result.transcript.append({"role": "bot", "text": reply.text})
        result.outcome = reply.outcome

    def _finish(self, result: ChatResult, state: ChatState) -> ChatResult:
        result.order_id, result.payment_id = state.order_id, state.payment_id
        if result.outcome == "pending":
            result.outcome = "failed"
        return result


def _remember_ids(state: ChatState, obs: dict[str, Any]) -> None:
    """Track order/payment ids from tool results so the ledger can be matched to the chat."""
    res = obs.get("result") or {}
    if obs["tool"] == "create_order" and res.get("order_id"):
        state.order_id = str(res["order_id"])
    if obs["tool"] == "charge" and res.get("payment_id"):
        state.payment_id = str(res["payment_id"])


def _as_dict(items: Any) -> dict[str, int]:
    """LLM brains sometimes pass the items dict as a JSON string."""
    if isinstance(items, str):
        items = json.loads(items)
    return {str(k): int(v) for k, v in dict(items).items()}


def _action_repr(action: Tool | Reply) -> dict[str, Any]:
    if isinstance(action, Tool):
        return {"tool": action.name, "args": action.args}
    return {"reply": action.text, "outcome": action.outcome}
