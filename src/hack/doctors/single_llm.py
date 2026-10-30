"""B2: ONE call to the big model with metrics, config and as much trace as fits a fixed budget.
It returns root causes + one patch + escalate yes/no. Apply once, replay once, no second try."""
from __future__ import annotations

import json
import re
from typing import Any

from hack.doctors.base import Diagnosis, Doctor, RootCause, register
from hack.doctors.environment import Environment
from hack.doctors.taxonomy import ROOT_CAUSES

CHARS_PER_TOKEN = 3.5

SYSTEM_TEMPLATE = """You are an on-call SRE for {description} You receive one incident: metrics, invariant
violations, the bot's control-panel config with its change history, chat transcripts and traces.
You can only change the bot through ONE control-panel patch (flat dotted keys). If no config change
can fix the problem (e.g. an upstream is down or money may have moved without an order), escalate
to a human and change nothing, or only make a containing change. Be precise and conservative.
Reply with ONE JSON object and nothing else."""


def system_for(env: Environment) -> str:
    return SYSTEM_TEMPLATE.format(description=env.patient.short_description)

OUTPUT_SPEC = """Return exactly this JSON shape:
{"root_causes": [{"label": "<one of the labels>", "confidence": 0.0-1.0, "explanation": "..."}],
 "patch": {"<dotted.knob>": <value>, ...},
 "escalate": true|false,
 "report": "<3-6 sentence incident report for the team>"}
root_causes are ranked, most likely first (max 3). patch may be {} (no change)."""


@register("single_llm")
class SingleLLM(Doctor):
    def treat(self, env: Environment) -> Diagnosis:
        budget = int(self.config.get("trace_token_budget", 8000))
        prompt = self.build_prompt(env, budget)
        raw = env.llm(prompt, role="big", system=system_for(env), max_tokens=int(self.config.get("max_tokens", 16000)),
                      purpose="diagnose+fix")
        answer = parse_answer(raw)
        if answer is None:
            return Diagnosis([], "model output was not valid JSON; no action taken")
        patch = answer.get("patch") or {}
        if isinstance(patch, dict) and patch:
            env.apply_patch(patch, "single_llm patch")
            env.replay()
        if answer.get("escalate"):
            env.escalate(str(answer.get("report", "escalated by single_llm")))
        causes = [RootCause(str(c.get("label", "unknown")), float(c.get("confidence", 0.5)), str(c.get("explanation", "")))
                  for c in answer.get("root_causes", []) if isinstance(c, dict)]
        return Diagnosis(causes, str(answer.get("report", "")))

    @staticmethod
    def build_prompt(env: Environment, trace_token_budget: int) -> str:
        metrics = env.read_metrics()
        per_chat = metrics.pop("per_chat", {})
        sections = [
            "## Root-cause labels\n" + "\n".join(f"- {k}: {v}" for k, v in ROOT_CAUSES.items()),
            "## Control-panel knobs\n" + "\n".join(f"- {k}: {v}" for k, v in env.describe_knobs().items()),
            "## Config (current) and change history\n" + _compact(env.read_config()),
            "## Metrics\n" + _compact(metrics) + "\nper chat: " + _compact(per_chat),
            "## Invariant violations\n" + _compact(env.read_invariants()),
            "## Chat transcripts\n" + "\n".join(
                f"[{c['chat_id']} -> {c['outcome']}] " + " | ".join(f"{t['role']}: {t['text']}" for t in c["transcript"])
                for c in env.read_chats()),
            "## Traces (errors and warnings first, then tool calls in order)\n" + trace_digest(env, trace_token_budget),
            OUTPUT_SPEC,
        ]
        return "\n\n".join(sections)


def trace_digest(env: Environment, token_budget: int) -> str:
    spans = env.read_traces(limit=None)
    important = [s for s in spans if s["status"]["code"] == "ERROR" or s["attributes"].get("log.severity") in ("WARN", "ERROR")]
    rest = [s for s in spans if s not in important and s["attributes"]["najda.kind"] in ("tool", "guard")]
    lines, used, budget = [], 0, int(token_budget * CHARS_PER_TOKEN)
    for s in important + rest:
        line = _span_line(s)
        if used + len(line) > budget:
            lines.append(f"... {len(important) + len(rest) - len(lines)} more spans omitted (budget)")
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


def _span_line(s: dict[str, Any]) -> str:
    a = s["attributes"]
    kind = a["najda.kind"]
    head = f"{a['chat.id']} {s['name']} [{s['status']['code']}]"
    ms = (s["end_time_unix_nano"] - s["start_time_unix_nano"]) / 1e6
    if kind == "tool":
        code = a.get("http.response.status_code")
        return f"{head} {ms:.0f}ms code={code} args={a['tool.args']} result={a['tool.result'][:200]} {s['status']['message'] or ''}".strip()
    if kind == "log":
        return f"{head} {a['log.severity']}: {a['log.message']}"
    return f"{head} {a.get('guard.args', '')} {s['status']['message'] or ''}".strip()


def _compact(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def parse_answer(text: str) -> dict[str, Any] | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group())
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
