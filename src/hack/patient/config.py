"""The control panel: the ONE place where everything Najda may change lives.

Changes are flat dotted-key patches ({"retry.max_retries": 3}), applied through ControlPanel so
every version is recorded and any version can be rolled back to (rollback is itself a new version).
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any

from hack.patient.prompts import PROMPTS

DEFAULT_FIELD_MAPPINGS = {
    "order_id": "order_id", "status": "status", "price": "price",
    "qty_available": "qty_available", "payment_id": "payment_id", "payment_status": "status",
}
DEFAULT_TOOLS = ["check_stock", "create_order", "get_order", "confirm_order", "charge",
                 "get_payment", "webhook_status"]


@dataclass
class RetryPolicy:
    max_retries: int = 0
    backoff_s: float = 0.5
    retry_on: list[int] = field(default_factory=lambda: [429, 503])


@dataclass
class AuthConfig:
    key_slot: str = "primary"  # "primary" | "backup": which secrets-manager key slot the bot uses


LEGACY_KEYS = ("auth_token",)  # bench v1 snapshots carried a raw token; dropped on load


@dataclass
class BotConfig:
    field_mappings: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_FIELD_MAPPINGS))
    prompt_version: str = "v1"
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    timeout_s: float = 3.0
    max_turns: int = 10
    allowed_tools: list[str] = field(default_factory=lambda: list(DEFAULT_TOOLS))
    price_unit: str = "sar"            # "sar" | "halalas"
    normalize_numerals: bool = False
    stock_fresh_read: bool = False
    payment_verify: str = "webhook"    # "webhook" | "query"
    auth: AuthConfig = field(default_factory=AuthConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BotConfig":
        d = {k: v for k, v in copy.deepcopy(d).items() if k not in LEGACY_KEYS}
        d["retry"] = RetryPolicy(**d.get("retry", {}))
        d["auth"] = AuthConfig(**d.get("auth", {}))
        return cls(**d)

    def patched(self, patch: dict[str, Any]) -> "BotConfig":
        d = self.to_dict()
        for key, value in patch.items():
            node = d
            parts = key.split(".")
            for p in parts[:-1]:
                node = node.setdefault(p, {})
            node[parts[-1]] = value
        return BotConfig.from_dict(d)


@dataclass
class ConfigVersion:
    version: int
    patch: dict[str, Any]
    reason: str
    actor: str
    time: float
    config: dict[str, Any]


class ControlPanel:
    """Versioned config of any patient. `config_cls` is the patient's config dataclass (to_dict / from_dict /
    patched); the order bot's BotConfig is the default so existing snapshots load unchanged."""

    def __init__(self, config: Any | None = None, time: float = 0.0, config_cls: type | None = None) -> None:
        self.config_cls = config_cls or (type(config) if config is not None else BotConfig)
        cfg = config if config is not None else self.config_cls()
        self.history: list[ConfigVersion] = [ConfigVersion(1, {}, "initial", "system", time, cfg.to_dict())]

    @property
    def current(self) -> Any:
        return self.config_cls.from_dict(self.history[-1].config)

    @property
    def version(self) -> int:
        return self.history[-1].version

    def apply(self, patch: dict[str, Any], reason: str, actor: str, time: float = 0.0) -> int:
        new = self.current.patched(patch)
        self.history.append(ConfigVersion(self.version + 1, dict(patch), reason, actor, time, new.to_dict()))
        return self.version

    def rollback(self, to_version: int, actor: str = "najda", time: float = 0.0) -> int:
        target = next(v for v in self.history if v.version == to_version)
        self.history.append(ConfigVersion(self.version + 1, {"_rollback_to": to_version},
                                          f"rollback to v{to_version}", actor, time, copy.deepcopy(target.config)))
        return self.version

    def snapshot(self) -> dict[str, Any]:
        return {"version": self.version, "current": self.current.to_dict(),
                "history": [asdict(v) for v in self.history]}

    @classmethod
    def from_snapshot(cls, snap: dict[str, Any], config_cls: type | None = None) -> "ControlPanel":
        panel = cls.__new__(cls)
        panel.config_cls = config_cls or BotConfig
        panel.history = [ConfigVersion(**v) for v in snap["history"]]
        return panel


KNOB_DOCS: dict[str, str] = {
    "field_mappings.<logical>": "which key in service responses holds each logical field "
                                "(order_id, status, price, qty_available, payment_id, payment_status)",
    "prompt_version": "active prompt; registered versions: " + ", ".join(sorted(PROMPTS)),
    "retry.max_retries": "retries per tool call on retry_on status codes (int, 0 = none)",
    "retry.backoff_s": "base backoff seconds, doubled each retry",
    "retry.retry_on": "HTTP status codes that trigger a retry",
    "timeout_s": "max seconds a single tool call may take before the bot gives up",
    "max_turns": "guard: max bot actions per chat before a polite failure",
    "allowed_tools": "tools the bot may call",
    "price_unit": "unit of StockAPI price field: 'sar' or 'halalas' (divided by 100)",
    "normalize_numerals": "convert Arabic-Indic digits (٠-٩) to 0-9 before parsing quantities",
    "stock_fresh_read": "ask StockAPI for fresh (uncached) reads",
    "payment_verify": "how to verify a charge: 'webhook' (wait for webhook) or 'query' (call get_payment)",
    "auth.key_slot": "which secrets-manager API key slot the bot uses for OrderAPI and PaymentAPI: 'primary' or 'backup'",
}


def flatten(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "."))
        else:
            out[key] = v
    return out


def diff_configs(before: dict[str, Any], after: dict[str, Any]) -> dict[str, tuple[Any, Any]]:
    """{dotted_key: (old, new)} for every knob that differs."""
    a, b = flatten(before), flatten(after)
    return {k: (a.get(k), b.get(k)) for k in sorted(a.keys() | b.keys()) if a.get(k) != b.get(k)}


def validate_patch(config: Any, patch: dict[str, Any]) -> str | None:
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
