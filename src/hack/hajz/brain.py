"""Hajz scripted brain: a deterministic state machine over the prompt's step list (no API key).

Observation is {"customer": text} or a tool observation {"tool", "ok", "result": {logical keys}, "error", "status"}.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from hack.hajz.calendar import RIYADH_OFFSET_H, RIYADH_TZ, UTC_TZ, BookingRequest, hijri_from_gregorian
from hack.hajz.config import DEPOSIT_PER_GUEST_SAR, BookingConfig
from hack.hajz.prompts import PROMPTS
from hack.patient.brains import Reply, Tool, is_arabic, is_yes

Action = Tool | Reply
BOOKING_YEAR = 2026  # the bench clock lives in January 2026; customers never type the year

PARTY_RE = re.compile(r"(?:لـ|ل|for)\s*(\d{1,2})\b|(\d{1,2})\s*(?:أشخاص|اشخاص|انفار|نفر|persons?|people|guests|pax)")
DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})\b")
TIME_RE = re.compile(r"(?:الساعة|الساعه|at)\s*(\d{1,2})(?::(\d{2}))?")


@dataclass
class BookingState:
    chat_id: str
    lang: str = "ar"
    request: BookingRequest | None = None
    booking_id: str | None = None
    deposit_id: str | None = None
    deposit_sar: float | None = None


def parse_request(text: str, date_format: str) -> BookingRequest | None:
    """Date (d/m or m/d per config), time (dinner: hours under 12 are evening) and party size."""
    m_party, m_date, m_time = PARTY_RE.search(text), DATE_RE.search(text), TIME_RE.search(text)
    if not (m_party and m_date and m_time):
        return None
    party = int(m_party.group(1) or m_party.group(2))
    a, b = int(m_date.group(1)), int(m_date.group(2))
    day_n, month = (a, b) if date_format == "dmy" else (b, a)
    try:
        day = date(BOOKING_YEAR, month, day_n)
    except ValueError:
        return None
    hour, minute = int(m_time.group(1)), int(m_time.group(2) or 0)
    if hour < 12:
        hour += 12
    return BookingRequest(day, hour, minute, party)


def slot_args(req: BookingRequest, cfg: BookingConfig) -> dict[str, Any]:
    """(date, time, tz) as the control panel says the APIs want them."""
    if cfg.timezone == "UTC":
        hour, day = req.hour - RIYADH_OFFSET_H, req.day
        tz = UTC_TZ
    else:
        hour, day, tz = req.hour, req.day, RIYADH_TZ
    date_s = hijri_from_gregorian(day) if cfg.calendar == "hijri" else day.isoformat()
    return {"date": date_s, "time": f"{hour:02d}:{req.minute:02d}", "tz": tz}


class BookingBrain:
    def __init__(self) -> None:
        self.config = BookingConfig()

    def start_chat(self, config: BookingConfig) -> None:
        self.config = config
        self.steps = list(PROMPTS[config.prompt_version].steps)
        self.step = 0
        self.phase = "await_request"

    def decide(self, state: BookingState, obs: dict[str, Any]) -> tuple[Action, int]:
        if "customer" in obs:
            return self._on_customer(state, obs["customer"]), 0
        return self._on_tool(state, obs), 0

    def _on_customer(self, state: BookingState, text: str) -> Action:
        state.lang = "ar" if is_arabic(text) else "en"
        if self.phase == "await_request":
            req = parse_request(text, self.config.date_format)
            if req is None:
                return self._fail(state, "ما فهمت التاريخ أو الوقت أو عدد الأشخاص، ممكن تعيدها؟",
                                  "Sorry, I couldn't read the date, time or party size. Could you repeat them?")
            state.request = req
            self.phase = "working"
            self.step = self.steps.index("check_availability") if "check_availability" in self.steps else 1
            return self._next(state)
        if self.phase == "await_confirm":
            if is_yes(text):
                self.phase = "working"
                return self._next(state)
            return Reply(_t(state, "تمام، ألغينا الحجز. نشوفك على خير!", "No problem, booking cancelled. See you soon!"), "declined")
        return self._fail(state, "صار خطأ، حاول مرة ثانية.", "Something went wrong, please try again.")

    def _on_tool(self, state: BookingState, obs: dict[str, Any]) -> Action:
        tool, res = obs["tool"], obs.get("result") or {}
        if not obs["ok"]:
            if tool == "check_availability":
                return self._fail(state, "ما قدرنا نتحقق من التوفر الحين، حاول بعد شوي.", "We couldn't check availability right now, please try again later.")
            if tool == "charge_deposit":
                return self._fail(state, "ما قدرنا نحصّل العربون، ما تم تأكيد الحجز.", "The deposit could not be charged, so the booking was not confirmed.")
            return self._fail(state, "صار خطأ أثناء الحجز، حاول مرة ثانية.", "Something went wrong while booking, please try again.")
        if tool == "check_availability":
            if not res.get("available"):
                self.phase = "done"
                return Reply(_t(state, "للأسف ما فيه طاولات متاحة في هذا الوقت.", "Sorry, there are no tables available at that time."), "declined")
            return self._next(state)
        if tool == "create_booking":
            if res.get("booking_id") is None:
                return self._fail(state, "صار خطأ أثناء الحجز، حاول مرة ثانية.", "Something went wrong while booking, please try again.")
            state.booking_id = str(res["booking_id"])
            state.deposit_sar = float(res.get("deposit_sar") or (state.request.party * DEPOSIT_PER_GUEST_SAR if state.request else 0))
            return self._next(state)
        if tool == "charge_deposit":
            if res.get("deposit_status") != "paid":
                return self._fail(state, "ما قدرنا نحصّل العربون، ما تم تأكيد الحجز.", "The deposit could not be charged, so the booking was not confirmed.")
            state.deposit_id = str(res.get("deposit_id"))
            return self._next(state)
        return self._next(state)

    def _next(self, state: BookingState) -> Action:
        req, cfg = state.request, self.config
        assert req is not None
        while self.step < len(self.steps):
            step = self.steps[self.step]
            self.step += 1
            if step == "check_availability":
                return Tool("check_availability", {**slot_args(req, cfg), "party_size": req.party})
            if step == "quote":
                self.phase = "await_confirm"
                deposit = req.party * DEPOSIT_PER_GUEST_SAR
                return Reply(_t(state, f"متاح يوم {req.day.day}/{req.day.month} الساعة {req.time_s} لـ {req.party} أشخاص. العربون {deposit:g} ريال. أأكد الحجز؟",
                                f"Available on {req.day.day}/{req.day.month} at {req.time_s} for {req.party}. Deposit {deposit:g} SAR. Shall I confirm?"), "pending")
            if step == "create_booking":
                return Tool("create_booking", {**slot_args(req, cfg), "party_size": req.party, "customer": state.chat_id})
            if step == "charge_deposit":
                return Tool("charge_deposit", {"booking_id": state.booking_id, "amount_sar": state.deposit_sar})
            if step == "send_confirmation":
                return Tool("send_confirmation", {"booking_id": state.booking_id})
            if step == "reply":
                return Reply(_t(state, f"تم تأكيد حجزك رقم {state.booking_id} يوم {req.day.day}/{req.day.month} الساعة {req.time_s}. شكراً لك!",
                                f"Your booking {state.booking_id} is confirmed for {req.day.day}/{req.day.month} at {req.time_s}. Thank you!"), "confirmed")
            if step != "parse":
                return Tool(step, {"booking_id": state.booking_id})
        return self._fail(state, "صار خطأ، حاول مرة ثانية.", "Something went wrong, please try again.")

    def _fail(self, state: BookingState, ar: str, en: str) -> Reply:
        self.phase = "done"
        return Reply(_t(state, ar, en), "failed")


def _t(state: BookingState, ar: str, en: str) -> str:
    return ar if state.lang == "ar" else en
