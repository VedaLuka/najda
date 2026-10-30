"""Incident report: bilingual one-line summary, impact, evidence, actions, recommended human action."""
from __future__ import annotations

import json
from typing import Any

from hack.doctors.environment import Environment


def impact(env: Environment) -> dict[str, Any]:
    failed = env.failed_chat_ids()
    metrics = env.read_metrics()
    sar = 0.0
    orders = 0
    for s in env.read_traces(kind="tool", name="create_order", limit=None):
        if s["attributes"]["chat.id"] not in failed or s["status"]["code"] == "ERROR":
            continue
        try:
            result = json.loads(s["attributes"]["tool.result"])
        except (TypeError, ValueError):
            continue
        if isinstance(result, dict):
            orders += 1
            sar += float(result.get("total_sar") or 0.0)
    return {"chats_affected": len(failed), "chats_total": metrics.get("chats", 0),
            "orders_created_unconfirmed": orders, "sar_at_stake": round(sar, 2)}


def bilingual_summary(status: str, label: str, imp: dict[str, Any]) -> str:
    n = imp["chats_affected"]
    ar = {"recovered": f"نجدة: تم إصلاح العطل ({label}) والتحقق منه، {n} محادثة تعافت، لا حاجة لتدخل بشري.",
          "contained": f"نجدة: تم احتواء العطل ({label}) جزئياً و تصعيده لإنسان، {n} محادثة متأثرة.",
          "escalated": f"نجدة: لم يُصلح العطل ({label}) بإعدادات البوت، تم التصعيد لإنسان، {n} محادثة متأثرة."}[status]
    en = {"recovered": f"Najda: fixed and verified ({label}); {n} chats recovered; no human action needed.",
          "contained": f"Najda: contained ({label}) but not fixed; escalated; {n} chats affected.",
          "escalated": f"Najda: not fixable from the control panel ({label}); escalated; {n} chats affected."}[status]
    return f"{ar} | {en}"


def build_report(env: Environment, status: str, label: str, summary: str, evidence: list[str],
                 tried: list[dict[str, Any]], human_action: str) -> str:
    imp = impact(env)
    lines = [bilingual_summary(status, label, imp), "",
             f"Summary: {summary}",
             f"Impact: {imp['chats_affected']}/{imp['chats_total']} chats failed, {imp['orders_created_unconfirmed']} "
             f"orders created but not completed, ~{imp['sar_at_stake']} SAR at stake.",
             "Evidence:"] + [f"  - {e}" for e in evidence[:8]]
    lines.append("Actions:")
    for t in tried:
        lines.append(f"  - {t['label']} patch {t['patch']}: {t['outcome']}")
    if not tried:
        lines.append("  - no config change made")
    lines.append(f"Recommended human action: {human_action}")
    return "\n".join(lines)
