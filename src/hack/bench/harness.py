"""Run one doctor on one incident. Truth is passed in from memory (preloaded before the seal)."""
from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any

from hack.bench.incidents import rerun
from hack.doctors.base import Doctor, Resolution
from hack.doctors.environment import Environment
from hack.patient.config import ControlPanel
from hack.patients import DEFAULT_PATIENT, get_patient


def make_replay_fn(truth: dict[str, Any], replay_brain: str = "scripted"):
    """Replay closure over an in-memory truth record. `replay_brain` = 'scripted' (deterministic, free) or
    'llm' (the patient's real LLM brain; milestone validation only)."""
    def replay_fn(panel: ControlPanel, chats: str | list[str] = "failed") -> dict[str, Any]:
        run = rerun(truth, panel, chats=chats, replay_brain=replay_brain)
        per_chat = run.chat_verdicts()
        n_pass = sum(v["pass"] for v in per_chat.values())
        return {"per_chat": per_chat, "n_pass": n_pass, "n_total": len(per_chat),
                "all_pass": n_pass == len(per_chat) and not run.violations,
                "invariants_ok": not run.violations,
                "violation_names": sorted({v.invariant for v in run.violations}),
                "violations": [v.to_dict() for v in run.violations],
                "error_digest": replay_digest(run, per_chat)}
    return replay_fn


def replay_digest(run, per_chat: dict[str, dict[str, Any]], max_lines: int = 30) -> list[str]:
    """Short digest of the rerun: errors and warnings first, then the tool calls of chats that still fail.
    Fresh evidence for a doctor's next round (a second fault often shows only after the first fix)."""
    failing = {c for c, v in per_chat.items() if not v["pass"]}
    lines: list[str] = []
    spans = run.world.tracer.spans
    important = [s for s in spans if s.error or s.level in ("WARN", "ERROR")]
    rest = [s for s in spans if s.kind == "tool" and not s.error and s.chat_id in failing]
    for s in important + rest:
        if len(lines) >= max_lines:
            lines.append(f"... {len(important) + len(rest) - max_lines} more spans")
            break
        code = f" code={s.status_code}" if s.status_code is not None else ""
        err = f" ERROR {s.error}" if s.error else (f" {s.level} {s.args.get('message', '')}" if s.kind == "log" else "")
        res = f" result={str(s.result)[:120]}" if s.kind == "tool" and s.result is not None else ""
        lines.append(f"replay {s.chat_id} {s.kind}.{s.name}{code}{err}{res}".rstrip())
    return lines


def treat_incident(doctor: Doctor, bundle: Path, truth: dict[str, Any],
                   replay_brain: str = "scripted") -> tuple[Resolution, dict[str, Any]]:
    """Returns the Resolution and the incident's starting config (for scoring). The Environment is built for
    the patient the incident belongs to (plumbing only: the doctor never sees the truth record)."""
    env = Environment(bundle, make_replay_fn(truth, replay_brain), patient=get_patient(truth.get("patient", DEFAULT_PATIENT)))
    if doctor.needs_truth:
        doctor.give_truth(truth)
    error = None
    try:
        diagnosis = doctor.treat(env)
        causes, report = diagnosis.root_causes, diagnosis.report
    except Exception as e:  # noqa: BLE001 - a crashing doctor is scored, not fatal
        causes, report = [], ""
        error = f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}"
    u = env.llm_usage
    resolution = Resolution(
        incident_id=env.incident_id, doctor=doctor.name, root_causes=causes, actions=env.actions,
        escalated=env.escalated, report=env.escalation_report or report, steps=env.steps,
        approvals_needed=sum(1 for s in env.steps if "approval" in s), llm_calls=u["calls"],
        input_tokens=u["input_tokens"], output_tokens=u["output_tokens"], cost_usd=round(u["cost_usd"], 6),
        wall_s=round(env.wall_s, 3), final_config=env.panel.current.to_dict(), error=error)
    return resolution, env.initial_config
