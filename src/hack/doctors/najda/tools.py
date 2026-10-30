"""Tool definitions the investigator sees, and the dispatcher that runs them on the Environment.
Results are digests capped in size so the conversation stays small."""
from __future__ import annotations

import json
from typing import Any

from hack.doctors.environment import Environment
from hack.doctors.single_llm import _span_line
from hack.doctors.taxonomy import ROOT_CAUSES

MAX_RESULT_CHARS = 6000

HYPOTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "root_cause": {"type": "string", "enum": sorted(ROOT_CAUSES)},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence_span_ids": {"type": "array", "items": {"type": "string"},
                              "description": "span ids (e.g. s00012) from the traces that support this hypothesis"},
        "rationale": {"type": "string", "description": "one or two sentences"},
        "patch": {"type": "object", "description": "smallest control-panel patch that would fix it; {} if none",
                  "additionalProperties": True},
    },
    "required": ["root_cause", "confidence", "evidence_span_ids", "rationale", "patch"],
}

TOOLS: list[dict[str, Any]] = [
    {"name": "search_traces",
     "description": "Search the incident's spans. Filters: kind (tool|log|guard|reply|customer|llm), name (span or "
                    "tool name), errors_only, search (substring over the span json), chat_id. Returns one line per span.",
     "input_schema": {"type": "object", "properties": {
         "kind": {"type": "string"}, "name": {"type": "string"}, "errors_only": {"type": "boolean"},
         "search": {"type": "string"}, "chat_id": {"type": "string"},
         "limit": {"type": "integer", "minimum": 1, "maximum": 80}}}},
    {"name": "read_metrics", "description": "Incident metrics (error rate, latency, orders created/paid/confirmed, "
                                            "per-chat outcome).", "input_schema": {"type": "object", "properties": {}}},
    {"name": "read_config", "description": "Current control-panel config and version.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "config_history_diff", "description": "Every config version with the knobs it changed, actor, reason.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "run_invariants", "description": "Invariant violations recorded for the incident (chat, rule, detail).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "read_chats", "description": "Chat transcripts with outcomes. Optional chat_id.",
     "input_schema": {"type": "object", "properties": {"chat_id": {"type": "string"}}}},
    {"name": "bisect_config", "description": "Replay the failed chats against older config versions to find the "
                                             "exact version that introduced the failure (free, deterministic).",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "apply_patch", "description": "Apply a control-panel patch (flat dotted keys). Guardrails may refuse it. "
                                           "Prefer proposing hypotheses and letting the controller apply them.",
     "input_schema": {"type": "object", "properties": {"patch": {"type": "object", "additionalProperties": True},
                                                       "reason": {"type": "string"}}, "required": ["patch"]}},
    {"name": "rollback", "description": "Roll the config back to a version.",
     "input_schema": {"type": "object", "properties": {"to_version": {"type": "integer"}, "reason": {"type": "string"}},
                      "required": ["to_version"]}},
    {"name": "replay", "description": "Rerun the failed chats with the current config; returns pass/fail per chat.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "escalate", "description": "Recommend escalation to a human with a reason. The controller decides.",
     "input_schema": {"type": "object", "properties": {"reason": {"type": "string"}}, "required": ["reason"]}},
    {"name": "propose_hypotheses",
     "description": "Finish the investigation: ranked hypotheses, most likely first. Each has one root-cause label, "
                    "evidence span ids, confidence 0-1 and the smallest patch that would fix it ({} if none).",
     "input_schema": {"type": "object", "properties": {
         "hypotheses": {"type": "array", "items": HYPOTHESIS_SCHEMA, "minItems": 1, "maxItems": 5},
         "escalate_recommended": {"type": "boolean"},
         "escalation_reason": {"type": "string"},
         "summary": {"type": "string", "description": "two-sentence incident summary for the report"},
         "recommended_human_action": {"type": "string"}},
         "required": ["hypotheses", "escalate_recommended", "summary"]}},
]


def tool_names(enable_bisect: bool) -> list[dict[str, Any]]:
    return [t for t in TOOLS if enable_bisect or t["name"] != "bisect_config"]


def run_read_tool(env: Environment, name: str, args: dict[str, Any]) -> str:
    """Read-only tools. Action tools (apply_patch, rollback, replay, escalate, propose_hypotheses,
    bisect_config) are handled by the controller."""
    if name == "search_traces":
        spans = env.read_traces(kind=args.get("kind"), name=args.get("name"), errors_only=bool(args.get("errors_only")),
                                search=args.get("search"), chat_id=args.get("chat_id"), limit=int(args.get("limit") or 40))
        return _cap("\n".join(f"{s['span_id']} {_span_line(s)}" for s in spans) or "no spans matched")
    if name == "read_metrics":
        return _cap(_compact(env.read_metrics()))
    if name == "read_config":
        snap = env.read_config()
        return _cap(_compact({"version": snap["version"], "current": snap["current"]}))
    if name == "config_history_diff":
        return _cap(_compact(env.config_history_diff()))
    if name == "run_invariants":
        return _cap(_compact(env.read_invariants()) if env.read_invariants() else "no invariant violations")
    if name == "read_chats":
        chats = env.read_chats()
        if args.get("chat_id"):
            chats = [c for c in chats if c["chat_id"] == args["chat_id"]]
        return _cap("\n".join(f"[{c['chat_id']} -> {c['outcome']}] " + " | ".join(f"{t['role']}: {t['text']}" for t in c["transcript"])
                              for c in chats) or "no such chat")
    return f"unknown tool {name}"


def _compact(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def _cap(text: str) -> str:
    return text if len(text) <= MAX_RESULT_CHARS else text[:MAX_RESULT_CHARS] + f"\n... truncated ({len(text)} chars)"
