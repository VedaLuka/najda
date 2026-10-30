"""Adapter: our JSONL spans -> OpenTelemetry-shaped span dicts.

Doctors read traces in this shape so the same code could read real production traces later.
Attribute values are primitives (complex args/results are JSON strings), as OTel requires.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

SPAN_KIND = {"tool": "CLIENT", "llm": "INTERNAL", "reply": "PRODUCER", "customer": "CONSUMER",
             "log": "INTERNAL", "guard": "INTERNAL"}


def trace_id(incident_id: str, chat_id: str) -> str:
    return hashlib.sha256(f"{incident_id}/{chat_id}".encode()).hexdigest()[:32]


def to_otel(span: dict[str, Any]) -> dict[str, Any]:
    kind = span["kind"]
    attrs: dict[str, Any] = {"najda.kind": kind, "incident.id": span["incident_id"], "chat.id": span["chat_id"]}
    if kind == "tool":
        attrs["tool.name"] = span["name"]
        attrs["tool.args"] = _json(span["args"])
        attrs["tool.result"] = _json(span["result"])
        if span["status_code"] is not None:
            attrs["http.response.status_code"] = span["status_code"]
    elif kind == "log":
        attrs["log.severity"] = span["level"]
        attrs["log.message"] = span["args"].get("message", "")
    elif kind in ("reply", "customer"):
        attrs["message.text"] = span["args"].get("text", "")
        if kind == "reply":
            attrs["reply.outcome"] = span["name"]
    elif kind == "llm":
        attrs["llm.decision"] = _json(span["result"])
        attrs["llm.tokens"] = span["tokens"]
    elif kind == "guard":
        attrs["guard.args"] = _json(span["args"])
    status = {"code": "ERROR", "message": span["error"]} if span["error"] else {"code": "OK" if kind == "tool" else "UNSET", "message": ""}
    return {
        "trace_id": trace_id(span["incident_id"], span["chat_id"]),
        "span_id": span["span_id"],
        "parent_span_id": span["parent_id"],
        "name": f"{kind}.{span['name']}" if kind != "tool" else f"tool.{span['name']}",
        "kind": SPAN_KIND.get(kind, "INTERNAL"),
        "start_time_unix_nano": int(span["t_start"] * 1e9),
        "end_time_unix_nano": int(span["t_end"] * 1e9),
        "status": status,
        "attributes": attrs,
    }


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
