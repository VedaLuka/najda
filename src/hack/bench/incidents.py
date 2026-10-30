"""Build, run and save incidents. An incident = fault(s) + seed + a handful of customer chats."""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hack.bench.chats import CHAT_SCRIPTS, SCRIPTS_BY_ID
from hack.bench.truth import write_truth
from hack.faults.catalog import COMBOS, apply_faults, merged_truth
from hack.patient.bot import ChatResult, OrderBot
from hack.patient.brains import Brain, ScriptedBrain
from hack.patient.clock import REPLAY_OFFSET_S
from hack.patient.config import ControlPanel
from hack.patient.invariants import Violation, check_invariants, order_completed
from hack.patient.tracing import metrics_from_spans
from hack.patient.world import World


@dataclass
class IncidentSpec:
    incident_id: str
    split: str
    seed: int
    fault_ids: list[str]
    noisy: bool = False
    chat_ids: list[str] = field(default_factory=list)

    @property
    def family(self) -> str:
        return "+".join(sorted({f for f in self.fault_ids}))


@dataclass
class IncidentRun:
    spec: IncidentSpec
    world: World
    results: list[ChatResult]
    violations: list[Violation]

    def chat_verdicts(self) -> dict[str, dict[str, Any]]:
        bad_chats = {v.chat_id for v in self.violations}
        out = {}
        for r in self.results:
            inv_ok = r.chat_id not in bad_chats
            done = order_completed(self.world, r)
            out[r.chat_id] = {"pass": inv_ok and done, "invariants_ok": inv_ok, "order_completed": done,
                              "outcome": r.outcome, "turns": r.turns}
        return out


def resolve_faults(fault_ids: list[str]) -> list[str]:
    out: list[str] = []
    for f in fault_ids:
        out += list(COMBOS.get(f, (f,)))
    return out


def pick_chats(seed: int, n_min: int = 5, n_max: int = 10) -> list[str]:
    rng = random.Random(f"chats-{seed}")
    return sorted(rng.sample([s.id for s in CHAT_SCRIPTS], rng.randint(n_min, n_max)))


def run_incident(spec: IncidentSpec, brain: Brain | None = None, chat_ids: list[str] | None = None,
                 extra_patch: dict[str, Any] | None = None, panel: ControlPanel | None = None,
                 later: bool = False) -> IncidentRun:
    """Run an incident. `panel` replaces the post-fault control panel (used to rerun under a doctor's
    config). `later=True` is a replay: it happens after the incident, so transient faults have cleared."""
    world = World.build(spec.seed, spec.incident_id, clock_offset_s=REPLAY_OFFSET_S if later else 0.0)
    apply_faults(world, resolve_faults(spec.fault_ids), spec.noisy)
    if panel is not None:
        world.panel = ControlPanel.from_snapshot(panel.snapshot())
    if extra_patch:
        world.panel.apply(extra_patch, "candidate fix", "najda", world.clock.now())
    bot = OrderBot(world, brain or ScriptedBrain())
    results = [bot.run_chat(SCRIPTS_BY_ID[c]) for c in (chat_ids or spec.chat_ids)]
    return IncidentRun(spec, world, results, check_invariants(world, results))


def spec_from_truth(truth: dict[str, Any]) -> IncidentSpec:
    return IncidentSpec(truth["incident_id"], truth["split"], truth["seed"], truth["fault_ids"],
                        truth["noisy"], truth["chat_ids"])


def rerun(truth: dict[str, Any], panel: ControlPanel, chats: str = "failed", brain: Brain | None = None) -> IncidentRun:
    """Rebuild the broken world from an in-memory truth record and rerun chats under `panel`, later in time.
    chats="failed" reruns the chats that failed in the incident (all chats if none failed)."""
    chat_ids = truth["failed_chats"] if chats == "failed" else truth["chat_ids"]
    return run_incident(spec_from_truth(truth), brain=brain, chat_ids=chat_ids or truth["chat_ids"],
                        panel=panel, later=True)


def save_bundle(run: IncidentRun, root: Path) -> Path:
    """Write the bundle Najda sees, and the ground truth it never sees (separate directory)."""
    spec, world = run.spec, run.world
    bundle = root / spec.split / spec.incident_id
    bundle.mkdir(parents=True, exist_ok=True)
    world.tracer.write(bundle / "traces.jsonl")
    spans = [json.loads(l) for l in (bundle / "traces.jsonl").read_text(encoding="utf-8").splitlines()]
    outcomes = {r.chat_id: r.outcome for r in run.results}
    metrics = metrics_from_spans(spans, outcomes)
    _dump(bundle / "metrics.json", metrics)
    _dump(bundle / "config.json", world.panel.snapshot())
    _dump(bundle / "chats.json", [{"chat_id": r.chat_id, "outcome": r.outcome, "transcript": r.transcript}
                                  for r in run.results])
    _dump(bundle / "invariants.json", [v.to_dict() for v in run.violations])
    verdicts = run.chat_verdicts()
    write_truth(bundle, {
        "incident_id": spec.incident_id, "split": spec.split, "seed": spec.seed,
        "fault_ids": spec.fault_ids, "resolved_fault_ids": resolve_faults(spec.fault_ids),
        "family": spec.family, "noisy": spec.noisy, "chat_ids": spec.chat_ids,
        "ground_truth": merged_truth(resolve_faults(spec.fault_ids)).to_dict(),
        "failed_chats": sorted(c for c, v in verdicts.items() if not v["pass"]),
        "chat_verdicts": verdicts,
    })
    return bundle


def index_line(run: IncidentRun, bundle: Path) -> dict[str, Any]:
    verdicts = run.chat_verdicts()
    return {"incident_id": run.spec.incident_id, "split": run.spec.split, "path": str(bundle),
            "n_chats": len(run.results), "chats_failed": sum(not v["pass"] for v in verdicts.values()),
            "violations": len(run.violations)}


def load_bundle(bundle: Path) -> dict[str, Any]:
    spans = [json.loads(l) for l in (bundle / "traces.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    return {"incident_id": bundle.name, "split": bundle.parent.name, "traces": spans,
            "metrics": json.loads((bundle / "metrics.json").read_text(encoding="utf-8")),
            "config": json.loads((bundle / "config.json").read_text(encoding="utf-8")),
            "chats": json.loads((bundle / "chats.json").read_text(encoding="utf-8")),
            "invariants": json.loads((bundle / "invariants.json").read_text(encoding="utf-8"))}


def _dump(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


# ------------------------------- the benchmark plan ---------------------------------

BENCH_VERSION = "1.1"  # 1.1: + transient_blip (dev), auth fix via key slot (dev); heldout frozen at 1.0
BENCH_VERSION_FILE = "BENCH_VERSION"

DEV_FAULTS = ["schema_drift", "prompt_regression", "rate_limit_429", "infinite_loop",
              "hallucinated_tool", "auth_expired_401"]
HELDOUT_FAULTS = ["price_unit_halalas", "arabic_numerals", "stale_stock", "dropped_payment_webhook",
                  "latency_timeouts"]


def bench_plan(small: bool = False) -> list[IncidentSpec]:
    """Fixed, seeded plan: dev ~37 incidents, heldout ~25. `small` keeps 1 of each kind."""
    k = 1 if small else None
    plan: list[tuple[str, list[str], bool]] = []
    for fid in DEV_FAULTS:
        plan += [("dev", [fid], False)] * (k or 4)
    plan += [("dev", ["combo_schema_rate"], False)] * (k or 2) + [("dev", ["combo_prompt_auth"], False)] * (k or 2)
    plan += [("dev", ["payment_down"], False)] * (k or 2) + [("dev", ["stock_corrupt"], False)] * (k or 2)
    plan += [("dev", ["healthy"], False)] * (k or 2)
    plan += [("dev", [f], True) for f in (["schema_drift", "rate_limit_429", "auth_expired_401"][:k] if k else ["schema_drift", "rate_limit_429", "auth_expired_401"])]
    plan += [("dev", ["transient_blip"], False)] * (k or 5)  # bench v1.1: appended, new ids only
    for fid in HELDOUT_FAULTS:
        plan += [("heldout", [fid], False)] * (k or 3)
    plan += [("heldout", ["combo_price_latency"], False)] * (k or 2) + [("heldout", ["combo_numerals_stale"], False)] * (k or 2)
    plan += [("heldout", ["ambiguous_payment"], False)] * (k or 2)
    plan += [("heldout", ["healthy"], False)]
    plan += [("heldout", [f], True) for f in (["price_unit_halalas", "stale_stock", "dropped_payment_webhook"][:k] if k else ["price_unit_halalas", "stale_stock", "dropped_payment_webhook"])]

    specs: list[IncidentSpec] = []
    counters = {"dev": 0, "heldout": 0}
    for split, faults, noisy in plan:
        counters[split] += 1
        seed = 1000 * (1 if split == "dev" else 2) + counters[split]
        spec = IncidentSpec(f"{split}-{counters[split]:03d}", split, seed, faults, noisy, pick_chats(seed))
        specs.append(spec)
    return specs
