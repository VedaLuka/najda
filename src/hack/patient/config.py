"""The control panel: the ONE place where everything Najda may change lives.

Changes are flat dotted-key patches ({"retry.max_retries": 3}), applied through ControlPanel so
every version is recorded and any version can be rolled back to (rollback is itself a new version).
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any

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
    auth_token: str = "tok_v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BotConfig":
        d = copy.deepcopy(d)
        d["retry"] = RetryPolicy(**d.get("retry", {}))
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
    def __init__(self, config: BotConfig | None = None, time: float = 0.0) -> None:
        cfg = config or BotConfig()
        self.history: list[ConfigVersion] = [ConfigVersion(1, {}, "initial", "system", time, cfg.to_dict())]

    @property
    def current(self) -> BotConfig:
        return BotConfig.from_dict(self.history[-1].config)

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
    def from_snapshot(cls, snap: dict[str, Any]) -> "ControlPanel":
        panel = cls.__new__(cls)
        panel.history = [ConfigVersion(**v) for v in snap["history"]]
        return panel
