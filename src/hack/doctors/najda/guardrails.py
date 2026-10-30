"""Guardrails in code, not in the prompt. Every verdict carries a reason and evidence."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from hack.doctors.environment import RISKY_KEYS, Environment

PAYMENT_TOOLS = {"charge", "get_payment", "webhook_status"}
MONEY_MOVED_INVARIANTS = {"payment_has_confirmed_order"}  # a payment exists with no confirmed order

# v3 knob policy. APPROVAL_GATED: risky, pass the approval gate (prompt rollback, payments, credentials).
# MONEY_REFUSED: refused outright while money is at risk (payments and credentials only, never the prompt).
APPROVAL_GATED = tuple(RISKY_KEYS)
MONEY_REFUSED = ("payment_verify", "auth.key_slot")


def is_approval_gated(key: str) -> bool:
    return key in APPROVAL_GATED or "payment" in key


def is_money_refused(key: str) -> bool:
    return key in MONEY_REFUSED or "payment" in key or key.startswith("auth.")


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


def money_at_risk_ledger(env: Environment) -> list[str]:
    """v3: structured facts only, no message matching.
    (a) invariant TYPE payment_has_confirmed_order (money moved, no confirmed order);
    (b) ledger mismatch: a successful charge whose amount differs from the order's total;
    (c) payment upstream failing: payment tool span with HTTP 5xx, or an error with no status code (timeout)."""
    evidence: list[str] = []
    for v in env.read_invariants():
        if v["invariant"] in MONEY_MOVED_INVARIANTS:
            evidence.append(f"invariant {v['invariant']} ({v['chat_id']})")
    totals: dict[str, float] = {}
    charges: list[tuple[str, str, float]] = []
    for s in env.read_traces(kind="tool", limit=None):
        a = s["attributes"]
        code = a.get("http.response.status_code")
        name = a["tool.name"]
        if s["status"]["code"] == "ERROR":
            if name in PAYMENT_TOOLS and (code is None or code >= 500):
                evidence.append(f"{s['span_id']}: {name} {'timeout' if code is None else code}")
            continue
        result = _json_dict(a.get("tool.result"))
        if name in ("create_order", "get_order") and "order_id" in result and "total_sar" in result:
            totals[str(result["order_id"])] = float(result["total_sar"])
        if name == "charge" and result.get("status") == "paid" and "amount_sar" in result:
            charges.append((s["span_id"], str(result.get("order_id")), float(result["amount_sar"])))
    for span_id, order_id, amount in charges:
        if order_id in totals and abs(totals[order_id] - amount) > 0.005:
            evidence.append(f"{span_id}: charge {amount} SAR != order {order_id} total {totals[order_id]} SAR")
    return evidence


def _json_dict(raw: Any) -> dict[str, Any]:
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def check_patch_v3(env: Environment, patch: dict[str, Any], max_knobs: int, money_evidence: list[str]) -> Verdict:
    keys = list(patch)
    if len(keys) > max_knobs:
        return Verdict(False, "blast_radius", f"patch touches {len(keys)} knobs, max {max_knobs}", keys)
    refused = [k for k in keys if is_money_refused(k)]
    if refused and money_evidence:
        return Verdict(False, "protected_knob_money_at_risk",
                       f"{refused} touch payments/credentials while money is at risk; escalate instead",
                       money_evidence[:5])
    gated = [k for k in keys if is_approval_gated(k)]
    if gated:
        return Verdict(True, "approval_gated", f"{gated} need approval (approval gate)", gated)
    return Verdict(True, "ok", "unprotected knobs within blast radius", keys)


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
