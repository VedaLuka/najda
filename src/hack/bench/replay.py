"""Najda's verify step: rerun an incident's failed chats under a candidate config patch.

Replay rebuilds the broken world (it reads the hidden truth file for the fault ids and seed) and
returns only pass/fail information. Najda must call this instead of reading _truth/.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hack.bench.incidents import IncidentSpec, run_incident
from hack.bench.truth import read_truth


@dataclass
class ReplayResult:
    incident_id: str
    per_chat: dict[str, dict[str, Any]]
    violations: list[dict[str, Any]] = field(default_factory=list)

    @property
    def n_total(self) -> int:
        return len(self.per_chat)

    @property
    def n_pass(self) -> int:
        return sum(v["pass"] for v in self.per_chat.values())

    @property
    def all_pass(self) -> bool:
        return self.n_total > 0 and self.n_pass == self.n_total

    @property
    def invariants_ok(self) -> bool:
        return all(v["invariants_ok"] for v in self.per_chat.values())

    def summary(self) -> dict[str, Any]:
        return {"incident_id": self.incident_id, "n_pass": self.n_pass, "n_total": self.n_total,
                "all_pass": self.all_pass, "invariants_ok": self.invariants_ok,
                "violations": sorted({v["invariant"] for v in self.violations})}


def replay(incident_dir: Path, patch: dict[str, Any] | None = None, chats: str = "failed") -> ReplayResult:
    truth = read_truth(Path(incident_dir))
    spec = IncidentSpec(truth["incident_id"], truth["split"], truth["seed"], truth["fault_ids"],
                        truth["noisy"], truth["chat_ids"])
    chat_ids = truth["failed_chats"] if chats == "failed" else truth["chat_ids"]
    if not chat_ids:
        chat_ids = truth["chat_ids"]
    run = run_incident(spec, chat_ids=chat_ids, extra_patch=patch or {})
    return ReplayResult(spec.incident_id, run.chat_verdicts(), [v.to_dict() for v in run.violations])
