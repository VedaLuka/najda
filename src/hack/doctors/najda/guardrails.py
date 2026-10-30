"""Guardrails in code, not in the prompt. Every verdict carries a reason and evidence."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hack.doctors.environment import RISKY_KEYS, Environment

PAYMENT_TOOLS = {"charge", "get_payment", "webhook_status"}
MONEY_MOVED_INVARIANTS = {"payment_has_confirmed_order"}  # a payment exists with no confirmed order


@dataclass
class Verdict:
    allowed: bool
    rule: str
    reason: str
    evidence: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "rule": self.rule, "reason": self.reason, "evidence": self.evidence}


def is_protected(key: str) -> bool:
    return key in RISKY_KEYS or "payment" in key


def money_at_risk(env: Environment) -> list[str]:
    """Evidence that money may have moved or may move unverifiably: payment upstream failing with 5xx or
    timeouts, or an invariant showing a payment without a confirmed order / an amount mismatch."""
    evidence = []
    for s in env.read_traces(kind="tool", errors_only=True, limit=None):
        a = s["attributes"]
        code = a.get("http.response.status_code")
        if a["tool.name"] in PAYMENT_TOOLS and (code is None or code >= 500):
            evidence.append(f"{s['span_id']}: {a['tool.name']} {code or 'timeout'} {s['status']['message'] or ''}".strip())
    for v in env.read_invariants():
        if v["invariant"] in MONEY_MOVED_INVARIANTS or "paid" in v["detail"]:
            evidence.append(f"invariant {v['invariant']} ({v['chat_id']}): {v['detail']}")
    return evidence


def check_patch(env: Environment, patch: dict[str, Any], max_knobs: int, money_evidence: list[str]) -> Verdict:
    keys = list(patch)
    if len(keys) > max_knobs:
        return Verdict(False, "blast_radius", f"patch touches {len(keys)} knobs, max {max_knobs}", keys)
    protected = [k for k in keys if is_protected(k)]
    if protected and money_evidence:
        return Verdict(False, "protected_knob_money_at_risk",
                       f"{protected} are protected and money is at risk; escalate instead", money_evidence[:5])
    if protected:
        return Verdict(True, "protected_knob_approval", f"{protected} need approval (approval gate)", protected)
    return Verdict(True, "ok", "unprotected knobs within blast radius", keys)


def regression(env: Environment, passing: list[str]) -> dict[str, Any]:
    """Replay the chats that passed in the incident under the current config. Any failure means the patch
    made things worse and must be rolled back."""
    if not passing:
        return {"checked": 0, "broke": []}
    r = env.replay(passing)
    broke = sorted(c for c, v in r["per_chat"].items() if not v["pass"])
    return {"checked": len(passing), "broke": broke}
