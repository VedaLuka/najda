"""Run one doctor on one incident. Truth is passed in from memory (preloaded before the seal)."""
from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any

from hack.bench.incidents import rerun
from hack.doctors.base import Doctor, Resolution
from hack.doctors.environment import Environment
from hack.patient.brains import Brain, LLMBrain, ScriptedBrain
from hack.patient.config import ControlPanel


def make_brain(replay_brain: str) -> Brain:
    """'scripted' (deterministic, free) or 'llm' (the real LLM patient; milestone validation only)."""
    return LLMBrain() if replay_brain == "llm" else ScriptedBrain()


def make_replay_fn(truth: dict[str, Any], replay_brain: str = "scripted"):
    def replay_fn(panel: ControlPanel) -> dict[str, Any]:
        run = rerun(truth, panel, chats="failed", brain=make_brain(replay_brain))
        per_chat = run.chat_verdicts()
        n_pass = sum(v["pass"] for v in per_chat.values())
        return {"per_chat": per_chat, "n_pass": n_pass, "n_total": len(per_chat),
                "all_pass": n_pass == len(per_chat) and not run.violations,
                "invariants_ok": not run.violations,
                "violation_names": sorted({v.invariant for v in run.violations}),
                "violations": [v.to_dict() for v in run.violations]}
    return replay_fn


def treat_incident(doctor: Doctor, bundle: Path, truth: dict[str, Any],
                   replay_brain: str = "scripted") -> tuple[Resolution, dict[str, Any]]:
    """Returns the Resolution and the incident's starting config (for scoring)."""
    env = Environment(bundle, make_replay_fn(truth, replay_brain))
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
