"""Dates and slots for Hajz: local Riyadh wall-clock, UTC offsets and a small Hijri table.

The Hijri table is an approximation of Umm al-Qura anchored on the months the bench uses (Jumada II 1447 to
Dhu al-Qa'dah 1447). Bot and services share this module, so what matters is that both sides agree.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

RIYADH_OFFSET_H = 3
RIYADH_TZ = "+03:00"
UTC_TZ = "+00:00"

HIJRI_MONTH_STARTS: dict[tuple[int, int], date] = {  # (hijri year, month) -> Gregorian first day (approx.)
    (1447, 6): date(2025, 11, 22), (1447, 7): date(2025, 12, 21), (1447, 8): date(2026, 1, 20),
    (1447, 9): date(2026, 2, 18), (1447, 10): date(2026, 3, 20), (1447, 11): date(2026, 4, 18),
}


def gregorian_from_hijri(text: str) -> date:
    """'1447-07-25' -> 2026-01-14. ValueError outside the table."""
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text.strip())
    if not m:
        raise ValueError(f"not a YYYY-MM-DD date: {text!r}")
    y, mo, d = int(m[1]), int(m[2]), int(m[3])
    if (y, mo) not in HIJRI_MONTH_STARTS or not 1 <= d <= 30:
        raise ValueError(f"date out of range for calendar hijri: {text}")
    return HIJRI_MONTH_STARTS[(y, mo)] + timedelta(days=d - 1)


def hijri_from_gregorian(g: date) -> str:
    starts = sorted(HIJRI_MONTH_STARTS.items(), key=lambda kv: kv[1])
    for (ym, start), (_, nxt) in zip(starts, starts[1:]):
        if start <= g < nxt:
            return f"{ym[0]:04d}-{ym[1]:02d}-{(g - start).days + 1:02d}"
    raise ValueError(f"date out of the Hijri table: {g.isoformat()}")


def parse_gregorian(text: str) -> date:
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text.strip())
    if not m:
        raise ValueError(f"not a YYYY-MM-DD date: {text!r}")
    return date(int(m[1]), int(m[2]), int(m[3]))


def offset_hours(tz: str) -> int:
    m = re.fullmatch(r"([+-])(\d{2}):(\d{2})", tz.strip())
    if not m:
        raise ValueError(f"bad tz offset: {tz!r}")
    return int(f"{m[1]}{m[2]}")


def slot_utc(day: date, time_s: str, tz: str) -> datetime:
    """Local wall-clock (day, 'HH:MM') at offset `tz` -> aware UTC datetime."""
    h, mi = (int(x) for x in time_s.split(":"))
    local = datetime(day.year, day.month, day.day, h, mi)
    return (local - timedelta(hours=offset_hours(tz))).replace(tzinfo=timezone.utc)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_riyadh(dt: datetime) -> str:
    return (dt + timedelta(hours=RIYADH_OFFSET_H)).strftime("%Y-%m-%d %H:%M")


@dataclass(frozen=True)
class BookingRequest:
    """What the customer asked for, in Riyadh local time."""
    day: date
    hour: int
    minute: int
    party: int

    @property
    def time_s(self) -> str:
        return f"{self.hour:02d}:{self.minute:02d}"

    @property
    def utc(self) -> datetime:
        return slot_utc(self.day, self.time_s, RIYADH_TZ)
