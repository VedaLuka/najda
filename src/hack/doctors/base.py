"""Doctor interface. A doctor gets an Environment for one incident and returns a Diagnosis;
the runner turns Environment state + Diagnosis into a Resolution."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from hack.doctors.environment import Environment


@dataclass
class RootCause:
    label: str
    confidence: float
    explanation: str = ""


@dataclass
class Diagnosis:
    root_causes: list[RootCause] = field(default_factory=list)  # ranked, most likely first
    report: str = ""


@dataclass
class Resolution:
    incident_id: str
    doctor: str
    root_causes: list[RootCause]
    actions: list[dict[str, Any]]
    escalated: bool
    report: str
    steps: list[dict[str, Any]]
    approvals_needed: int
    llm_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    wall_s: float
    final_config: dict[str, Any]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Doctor:
    name = "base"
    needs_truth = False  # only the oracle; the runner hands it the truth record

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.memory: dict[str, Any] = {}  # persists across incidents when the runner keeps memory on

    def reset_memory(self) -> None:
        self.memory = {}

    def treat(self, env: Environment) -> Diagnosis:
        raise NotImplementedError


DOCTORS: dict[str, type[Doctor]] = {}


def register(name: str) -> Callable[[type[Doctor]], type[Doctor]]:
    def wrap(cls: type[Doctor]) -> type[Doctor]:
        if name in DOCTORS:
            raise ValueError(f"Doctor '{name}' already registered")
        cls.name = name
        DOCTORS[name] = cls
        return cls
    return wrap


def get_doctor(name: str, config: dict[str, Any] | None = None) -> Doctor:
    if name not in DOCTORS:
        raise KeyError(f"Unknown doctor '{name}'. Known: {sorted(DOCTORS)}")
    return DOCTORS[name](config)
