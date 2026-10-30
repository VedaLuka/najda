"""Cheap triage: one small-model call that classifies the incident and writes a compact evidence brief,
so the big model's first context is shorter. Healthy and transient incidents never reach it: code rules
handle those for free. The brief is advisory; the controller and the guardrails do not read it."""
from __future__ import annotations

import json
import re
from typing import Any

from hack.doctors.environment import Environment

CLASSES = ("money-at-risk", "config-regression", "upstream-failure", "novel")

SYSTEM_TEMPLATE = """You are the triage nurse for an on-call SRE agent that fixes %s. You get a compact incident digest. Reply with JSON only:
{"class": one of %s,
 "brief": "<= 120 words: what the failing chats do that passing chats do not, which tool/status/field is involved,
           whether a recent config change lines up with the failures, what to inspect first",
 "suspect_knobs": ["<control-panel knob>", ...]}
Do not invent evidence. Cite span ids from the digest where you can."""


def system_for(env: Environment) -> str:
    return SYSTEM_TEMPLATE % (env.patient.triage_description, json.dumps(CLASSES))


def run_triage(env: Environment, differential_digest: str, money: list[str], history: list[dict[str, Any]],
               transcripts: str, trace_digest: str, max_tokens: int = 500) -> dict[str, Any]:
    metrics = env.read_metrics()
    metrics.pop("per_chat", None)
    prompt = "\n\n".join([
        f"# Incident {env.incident_id}",
        "## Metrics\n" + json.dumps(metrics, ensure_ascii=False, separators=(",", ":")),
        "## Invariant violations\n" + (json.dumps(env.read_invariants()[:8], ensure_ascii=False) or "none"),
        "## Config change history\n" + (json.dumps(history, ensure_ascii=False, default=str) or "no changes"),
        "## Money at risk\n" + ("\n".join(money[:3]) or "no structured evidence"),
        "## Differential (failing vs passing chats)\n" + differential_digest,
        "## Transcript sample\n" + transcripts,
        "## Trace digest\n" + trace_digest,
    ])
    text = env.llm(prompt, role="triage", system=system_for(env), max_tokens=max_tokens, purpose="triage")
    out = _parse(text)
    env.record("triage", out)
    return out


def _parse(text: str) -> dict[str, Any]:
    m = re.search(r"\{.*\}", text, re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except ValueError:
        data = {}
    cls = str(data.get("class", "novel"))
    return {"class": cls if cls in CLASSES else "novel", "brief": str(data.get("brief", text))[:1200],
            "suspect_knobs": [str(k) for k in (data.get("suspect_knobs") or [])][:5], "parsed": bool(data)}
