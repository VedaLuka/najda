"""Two brains behind one interface. The bot asks `decide(state, observation)` and gets an Action.

Observation is either {"customer": text} or a tool observation
{"tool": name, "ok": bool, "result": {...logical keys...}, "error": str|None, "status": int|None}.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from hack.patient.config import BotConfig
from hack.patient.menu import MENU, find_sku
from hack.patient.numerals import normalize_digits, parse_quantity
from hack.patient.prompts import PROMPTS

YES_WORDS = ("yes", "yeah", "ok", "okay", "confirm", "sure", "نعم", "ايوه", "أيوه", "ايوا", "اي", "أي",
             "اوكي", "أوكي", "تمام", "اكيد", "أكيد", "ماشي", "يلا", "موافق")
NO_WORDS = ("no", "cancel", "nah", "لا", "الغي", "ألغي", "خلاص لا", "ما ابغى", "ماابغى")


@dataclass
class Tool:
    name: str
    args: dict[str, Any]


@dataclass
class Reply:
    text: str
    outcome: str  # pending | confirmed | declined | failed


Action = Tool | Reply


@dataclass
class ChatState:
    chat_id: str
    lang: str = "ar"
    cart: dict[str, int] = field(default_factory=dict)
    total_sar: float | None = None
    order_id: str | None = None
    payment_id: str | None = None


class Brain(Protocol):
    def start_chat(self, config: BotConfig) -> None: ...
    def decide(self, state: ChatState, observation: dict[str, Any]) -> tuple[Action, int]: ...


# ---------------------------------------------------------------------------
# Order parsing (shared helpers)
# ---------------------------------------------------------------------------

def parse_order(text: str, normalize_numerals: bool) -> dict[str, int]:
    """Find menu aliases in the message; the quantity is the number just before each item (default 1)."""
    if normalize_numerals:
        text = normalize_digits(text)
    low = text.lower()
    hits: list[tuple[int, int, str]] = []
    for item in MENU.values():
        for alias in item.aliases:
            for m in re.finditer(re.escape(alias), low):
                hits.append((m.start(), m.end(), item.sku))
    hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    chosen: list[tuple[int, int, str]] = []
    for h in hits:
        if not chosen or h[0] >= chosen[-1][1]:
            chosen.append(h)
    cart: dict[str, int] = {}
    prev_end = 0
    for start, end, sku in chosen:
        qty = parse_quantity(low[prev_end:start]) or 1
        cart[sku] = cart.get(sku, 0) + qty
        prev_end = end
    return cart


def is_arabic(text: str) -> bool:
    return bool(re.search(r"[؀-ۿ]", text))


def is_yes(text: str) -> bool:
    low = text.lower().strip()
    if any(_word_in(w, low) for w in NO_WORDS):
        return False
    return any(_word_in(w, low) for w in YES_WORDS)


def _word_in(word: str, text: str) -> bool:
    return re.search(rf"(^|\s){re.escape(word)}(\s|$|[!.،,])", text) is not None


def fmt_cart(cart: dict[str, int], lang: str) -> str:
    return ", ".join(f"{q} x {MENU[s].name_ar if lang == 'ar' else MENU[s].name_en}" for s, q in cart.items())


# ---------------------------------------------------------------------------
# Scripted brain: a deterministic state machine over the prompt's step list.
# ---------------------------------------------------------------------------

class ScriptedBrain:
    def __init__(self) -> None:
        self.config = BotConfig()

    def start_chat(self, config: BotConfig) -> None:
        self.config = config
        self.steps = list(PROMPTS[config.prompt_version].steps)
        self.step = 0
        self.phase = "await_order"
        self.stock_queue: list[str] = []
        self.pending_tool: str | None = None

    def decide(self, state: ChatState, obs: dict[str, Any]) -> tuple[Action, int]:
        if "customer" in obs:
            return self._on_customer(state, obs["customer"]), 0
        return self._on_tool(state, obs), 0

    def _on_customer(self, state: ChatState, text: str) -> Action:
        state.lang = "ar" if is_arabic(text) else "en"
        if self.phase == "await_order":
            cart = parse_order(text, self.config.normalize_numerals)
            if not cart:
                return self._fail(state, "ما فهمت الطلب، ممكن تعيده؟", "Sorry, I didn't catch the order. Could you repeat it?")
            state.cart = cart
            state.total_sar = 0.0
            self.stock_queue = list(cart)
            self.phase = "working"
            self.step = self.steps.index("check_stock") if "check_stock" in self.steps else 1
            return self._next(state)
        if self.phase == "await_confirm":
            if is_yes(text):
                self.phase = "working"
                return self._next(state)
            return Reply(_t(state, "تمام، ألغينا الطلب. نشوفك على خير!", "No problem, order cancelled. See you soon!"), "declined")
        return self._fail(state, "صار خطأ، حاول مرة ثانية.", "Something went wrong, please try again.")

    def _on_tool(self, state: ChatState, obs: dict[str, Any]) -> Action:
        name, res = obs["tool"], obs.get("result") or {}
        if not obs["ok"]:
            if name in ("charge", "get_payment", "webhook_status"):
                return self._fail(state, "ما قدرنا نكمل الدفع، حاول بعد شوي.", "We couldn't complete the payment, please try again shortly.")
            return self._fail(state, "النظام فيه مشكلة حالياً، حاول بعد شوي.", "Our system is having trouble right now, please try again shortly.")
        if name == "check_stock":
            sku = obs["args"]["sku"]
            if res.get("qty_available") is None or res["qty_available"] < state.cart[sku]:
                return self._fail(state, f"للأسف {MENU[sku].name_ar} غير متوفر حالياً.", f"Sorry, {MENU[sku].name_en} is out of stock right now.")
            state.total_sar = round((state.total_sar or 0.0) + (res.get("price") or 0.0) * state.cart[sku], 2)
            return self._next(state)
        if name == "create_order":
            if not res.get("order_id"):
                return self._fail(state, "النظام فيه مشكلة حالياً، حاول بعد شوي.", "Our system is having trouble right now, please try again shortly.")
            state.order_id = res["order_id"]
            if res.get("status") != "created":
                return Tool("get_order", {"order_id": state.order_id})
            return self._next(state)
        if name == "get_order":
            if res.get("status") != "created":
                return Tool("get_order", {"order_id": state.order_id})
            return self._next(state)
        if name == "charge":
            state.payment_id = res.get("payment_id")
            if self.config.payment_verify == "query":
                return Tool("get_payment", {"payment_id": state.payment_id})
            return Tool("webhook_status", {"order_id": state.order_id})
        if name in ("get_payment", "webhook_status"):
            if res.get("payment_status") != "paid":
                return self._fail(state, "الدفع ما اكتمل، ما تم تأكيد الطلب.", "The payment did not go through, so the order was not confirmed.")
            return self._next(state)
        return self._next(state)

    def _next(self, state: ChatState) -> Action:
        """Emit the action for the current step and advance."""
        while self.step < len(self.steps):
            step = self.steps[self.step]
            if step == "check_stock":
                if self.stock_queue:
                    return Tool("check_stock", {"sku": self.stock_queue.pop(0)})
                self.step += 1
                continue
            self.step += 1
            if step == "quote":
                self.phase = "await_confirm"
                return Reply(_t(state, f"طلبك: {fmt_cart(state.cart, 'ar')}. الإجمالي {state.total_sar:g} ريال. أأكد الطلب؟",
                                f"Your order: {fmt_cart(state.cart, 'en')}. Total {state.total_sar:g} SAR. Shall I confirm?"), "pending")
            if step == "create_order":
                return Tool("create_order", {"items": dict(state.cart), "total_sar": state.total_sar})
            if step == "charge":
                return Tool("charge", {"order_id": state.order_id, "amount_sar": state.total_sar})
            if step == "confirm_order":
                return Tool("confirm_order", {"order_id": state.order_id})
            if step == "reply":
                return Reply(_t(state, f"تم تأكيد طلبك رقم {state.order_id}. شكراً لك!",
                                f"Your order {state.order_id} is confirmed. Thank you!"), "confirmed")
            if step not in ("parse",):
                return Tool(step, {"order_id": state.order_id})
        return self._fail(state, "صار خطأ، حاول مرة ثانية.", "Something went wrong, please try again.")

    def _fail(self, state: ChatState, ar: str, en: str) -> Reply:
        self.phase = "done"
        return Reply(_t(state, ar, en), "failed")


def _t(state: ChatState, ar: str, en: str) -> str:
    return ar if state.lang == "ar" else en


# ---------------------------------------------------------------------------
# LLM brain: same interface, decisions come from hack.llm.call_llm (cached, temperature 0).
# ---------------------------------------------------------------------------

TOOL_SCHEMAS = {
    "check_stock": {"sku": "menu sku"},
    "create_order": {"items": "{sku: qty}", "total_sar": "number"},
    "get_order": {"order_id": "str"},
    "confirm_order": {"order_id": "str"},
    "charge": {"order_id": "str", "amount_sar": "number"},
    "get_payment": {"payment_id": "str"},
    "webhook_status": {"order_id": "str"},
}


class LLMBrain:
    def __init__(self, model: str | None = None) -> None:
        self.model = model
        self.config = BotConfig()
        self.messages: list[dict[str, str]] = []

    def start_chat(self, config: BotConfig) -> None:
        self.config = config
        self.messages = []

    def system_prompt(self) -> str:
        menu = "\n".join(f"- {m.sku}: {m.name_en} / {m.name_ar} — {m.price_sar:g} SAR" for m in MENU.values())
        tools = "\n".join(f"- {t}: args {json.dumps(TOOL_SCHEMAS.get(t, {}))}" for t in self.config.allowed_tools)
        verify = "get_payment" if self.config.payment_verify == "query" else "webhook_status"
        return (f"{PROMPTS[self.config.prompt_version].system_text}\n\nMenu:\n{menu}\n\nTools:\n{tools}\n\n"
                f"After charging, verify the payment with {verify} before confirm_order. "
                "Only confirm_order when payment status is paid.")

    def decide(self, state: ChatState, obs: dict[str, Any]) -> tuple[Action, int]:
        from hack.llm import STATS, call_llm

        if "customer" in obs:
            state.lang = "ar" if is_arabic(obs["customer"]) else "en"
            self.messages.append({"role": "user", "content": f"CUSTOMER: {obs['customer']}"})
        else:
            self.messages.append({"role": "user", "content": "TOOL RESULT: " + json.dumps(obs, ensure_ascii=False)})
        before = STATS["input_tokens"] + STATS["output_tokens"]
        text = call_llm(self.messages, model=self.model, temperature=0.0, system=self.system_prompt(), max_tokens=300)
        tokens = STATS["input_tokens"] + STATS["output_tokens"] - before
        self.messages.append({"role": "assistant", "content": text})
        return _parse_action(text, state), tokens


def _parse_action(text: str, state: ChatState) -> Action:
    m = re.search(r"\{.*\}", text, re.S)
    try:
        data = json.loads(m.group()) if m else {}
    except json.JSONDecodeError:
        data = {}
    if isinstance(data, dict) and "tool" in data:
        args = data.get("args")
        return Tool(str(data["tool"]), dict(args) if isinstance(args, dict) else {})
    if isinstance(data, dict) and "reply" in data:
        return Reply(str(data["reply"]), str(data.get("outcome", "pending")))
    return Reply(_t(state, "صار خطأ، حاول مرة ثانية.", "Something went wrong, please try again."), "failed")
