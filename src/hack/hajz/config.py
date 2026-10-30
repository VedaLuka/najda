"""Hajz control panel: the ONE place where everything a doctor may change lives. Flat dotted-key patches,
versioned through the shared ControlPanel (hack.patient.config)."""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any

from hack.hajz.prompts import PROMPTS
from hack.patient.config import AuthConfig, RetryPolicy, flatten

DEFAULT_FIELD_MAPPINGS = {
    "booking_id": "booking_id", "status": "status", "available": "available", "tables_left": "tables_left",
    "slot_time": "slot_time", "deposit_sar": "deposit_sar", "deposit_id": "deposit_id", "deposit_status": "status",
}
DEFAULT_TOOLS = ["check_availability", "create_booking", "get_booking", "charge_deposit", "send_confirmation"]
DEPOSIT_PER_GUEST_SAR = 20.0


@dataclass
class BookingConfig:
    field_mappings: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_FIELD_MAPPINGS))
    prompt_version: str = "v1"
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    timeout_s: float = 3.0
    max_turns: int = 10
    allowed_tools: list[str] = field(default_factory=lambda: list(DEFAULT_TOOLS))
    timezone: str = "Asia/Riyadh"      # "Asia/Riyadh" | "UTC": how slot times are serialised for the APIs
    date_format: str = "dmy"           # "dmy" | "mdy": how numeric dates typed by customers are read
    calendar: str = "gregorian"        # "gregorian" | "hijri": calendar of the date field sent to the APIs
    availability_fresh_read: bool = False
    auth: AuthConfig = field(default_factory=AuthConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BookingConfig":
        d = copy.deepcopy(d)
        d["retry"] = RetryPolicy(**d.get("retry", {}))
        d["auth"] = AuthConfig(**d.get("auth", {}))
        return cls(**d)

    def patched(self, patch: dict[str, Any]) -> "BookingConfig":
        d = self.to_dict()
        for key, value in patch.items():
            node = d
            parts = key.split(".")
            for p in parts[:-1]:
                node = node.setdefault(p, {})
            node[parts[-1]] = value
        return BookingConfig.from_dict(d)


KNOB_DOCS: dict[str, str] = {
    "field_mappings.<logical>": "which key in service responses holds each logical field (booking_id, status, "
                                "available, tables_left, slot_time, deposit_sar, deposit_id, deposit_status)",
    "prompt_version": "active prompt; registered versions: " + ", ".join(sorted(PROMPTS)),
    "retry.max_retries": "retries per tool call on retry_on status codes (int, 0 = none)",
    "retry.backoff_s": "base backoff seconds, doubled each retry",
    "retry.retry_on": "HTTP status codes that trigger a retry",
    "timeout_s": "max seconds a single tool call may take before the bot gives up",
    "max_turns": "guard: max bot actions per chat before a polite failure",
    "allowed_tools": "tools the bot may call",
    "timezone": "how the bot serialises slot times for AvailabilityAPI and BookingAPI: 'Asia/Riyadh' sends the "
                "customer's local wall-clock time with offset +03:00; 'UTC' converts it to UTC first and sends +00:00",
    "date_format": "how numeric dates typed by customers (two numbers separated by '/') are read: 'dmy' = day/month, "
                   "'mdy' = month/day",
    "calendar": "calendar of the date field the bot sends to the scheduling APIs: 'gregorian' (YYYY-MM-DD) or "
                "'hijri' (Umm al-Qura YYYY-MM-DD, converted by the bot before sending)",
    "availability_fresh_read": "ask AvailabilityAPI for a fresh (uncached) read",
    "auth.key_slot": "which secrets-manager API key slot the bot uses for BookingAPI and DepositAPI: 'primary' or 'backup'",
}


def validate_patch(config: BookingConfig, patch: dict[str, Any]) -> str | None:
    """None if the patch is applicable, else a reason. New field_mappings keys are allowed."""
    known = flatten(config.to_dict())
    for key in patch:
        if key not in known and not key.startswith("field_mappings."):
            return f"unknown knob: {key}"
    try:
        config.patched(patch)
    except (TypeError, ValueError) as e:
        return f"invalid patch: {e}"
    return None
