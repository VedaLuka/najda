"""Patient registry: everything a doctor or the bench needs from WHICHEVER agent is under treatment.

Two halves, kept apart on purpose:
- `Patient` (doctor-facing): how the agent describes itself, its control-panel config class and knob docs, which
  knobs are protected, which tools and invariants move money. Doctors read it through `Environment.patient`;
  nothing in `hack.doctors` imports a concrete patient.
- `PatientBench` (bench-facing): how to build and break its world, run its chats, check its invariants, and its
  fault catalog with the hidden ground truth. Only the generator, replay and scorer see it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

DEFAULT_PATIENT = "order"


class ConfigLike(Protocol):
    def to_dict(self) -> dict[str, Any]: ...
    def patched(self, patch: dict[str, Any]) -> "ConfigLike": ...


LedgerEntry = tuple[str, str, float]  # ("expected" | "charged", reference id, amount)


@dataclass(frozen=True)
class Patient:
    name: str
    # ---- how the patient describes itself to a doctor (plain text, no fault knowledge) ----
    description: str          # one or two sentences: what the bot does and which upstreams it calls
    short_description: str    # the same for one-call doctors
    triage_description: str   # parenthetical for the triage nurse
    knob_docs: dict[str, str]
    record_noun: str          # what a chat produces: "orders", "bookings" (for impact lines)
    # ---- control panel ----
    config_cls: type
    validate_patch: Callable[[Any, dict[str, Any]], str | None]
    protected_knobs: tuple[str, ...]            # approval-gated knobs
    protected_markers: tuple[str, ...]          # substrings that make any knob approval-gated
    money_knobs: tuple[str, ...]                # refused outright while money is at risk
    money_prefixes: tuple[str, ...]             # knob prefixes refused while money is at risk
    # ---- money ----
    payment_tools: frozenset[str]
    money_invariants: frozenset[str]            # invariant types that mean money moved without its record
    money_detail_marker: str                    # word in an invariant detail that means money moved
    ledger_entry: Callable[[str, dict[str, Any]], LedgerEntry | None]   # (tool, result) -> expected / charged
    committed_amount: Callable[[str, dict[str, Any]], float | None]    # (tool, result) -> amount of a record created
    api_contract: dict[str, set[str]]           # documented response keys per tool (from the API docs)

    def is_approval_gated(self, key: str) -> bool:
        return key in self.protected_knobs or any(m in key for m in self.protected_markers)

    def is_money_refused(self, key: str) -> bool:
        return key in self.money_knobs or any(m in key for m in self.protected_markers) \
            or any(key.startswith(p) for p in self.money_prefixes)


@dataclass(frozen=True)
class PatientBench:
    name: str
    build_world: Callable[..., Any]             # (seed, incident_id, clock_offset_s) -> world with .panel/.tracer/.clock
    apply_faults: Callable[..., None]           # (world, fault_ids, noisy, modifiers, noise_level)
    make_bot: Callable[[Any, Any], Any]         # (world, brain) -> bot with run_chat(script)
    make_brain: Callable[[str], Any]            # "scripted" | "llm"
    scripts: dict[str, Any]                     # chat id -> script
    check_invariants: Callable[[Any, list[Any]], list[Any]]
    completed: Callable[[Any, Any], bool]       # (world, chat result) -> did the customer get what they asked
    metrics_from_spans: Callable[[list[dict[str, Any]], dict[str, str]], dict[str, Any]]
    faults: dict[str, Any]                      # fault id -> Fault (apply + hidden truth)
    combos: dict[str, tuple[str, ...]]
    fault_labels: dict[str, set[str]]           # acceptable root-cause labels per fault (scorer only)
    merged_truth: Callable[[list[str]], Any]


Factory = Callable[[], tuple[Patient, PatientBench]]
_REGISTRY: dict[str, Factory] = {}


def register(name: str) -> Callable[[Factory], Factory]:
    def wrap(factory: Factory) -> Factory:
        _REGISTRY[name] = factory
        return factory
    return wrap


def _factory(name: str | None) -> Factory:
    name = name or DEFAULT_PATIENT
    if name not in _REGISTRY:
        _load_builtin(name)
    if name not in _REGISTRY:
        raise KeyError(f"unknown patient '{name}'; known: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def get_patient(name: str | None = None) -> Patient:
    """The doctor-facing half: safe to hand to a doctor (holds no faults, no truth)."""
    return _factory(name)()[0]


def get_bench(name: str | None = None) -> PatientBench:
    """The bench-facing half: world, chats, invariants and the fault catalog with ground truth."""
    return _factory(name)()[1]


def _load_builtin(name: str) -> None:
    """Import the module that registers a built-in patient (lazy: avoids import cycles)."""
    import importlib

    modules = {"order": "hack.patient.spec", "hajz": "hack.hajz.spec"}
    if name in modules:
        importlib.import_module(modules[name])
