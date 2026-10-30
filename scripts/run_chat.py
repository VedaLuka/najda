"""Run one chat against the patient bot, optionally under faults and a candidate fix.

  python scripts/run_chat.py --fault schema_drift
  python scripts/run_chat.py --fault schema_drift --fix '{"field_mappings.order_id": "id"}'
  python scripts/run_chat.py --brain llm --chat en_01            # needs an LLM key in .env
Prints a short summary; full traces go to --out (default experiments/chat_traces.jsonl).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hack.bench.chats import SCRIPTS_BY_ID  # noqa: E402
from hack.faults.catalog import FAULTS, apply_faults  # noqa: E402
from hack.patient.bot import OrderBot  # noqa: E402
from hack.patient.brains import LLMBrain, ScriptedBrain  # noqa: E402
from hack.patient.invariants import check_invariants, order_completed  # noqa: E402
from hack.patient.world import World  # noqa: E402

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat", default="ar_01", help=f"one of {sorted(SCRIPTS_BY_ID)}")
    ap.add_argument("--fault", default="", help=f"comma-separated ids from {sorted(FAULTS)}")
    ap.add_argument("--fix", default="", help='JSON control-panel patch, e.g. {"timeout_s": 8}')
    ap.add_argument("--brain", default="scripted", choices=["scripted", "llm"])
    ap.add_argument("--noisy", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=str(ROOT / "experiments" / "chat_traces.jsonl"))
    a = ap.parse_args()

    world = World.build(a.seed)
    apply_faults(world, [f for f in a.fault.split(",") if f], a.noisy)
    if a.fix:
        world.panel.apply(json.loads(a.fix), "manual fix", "cli", world.clock.now())
    brain = LLMBrain() if a.brain == "llm" else ScriptedBrain()
    result = OrderBot(world, brain).run_chat(SCRIPTS_BY_ID[a.chat])
    violations = check_invariants(world, [result])
    world.tracer.write(Path(a.out))

    print(f"chat={a.chat} faults={a.fault or 'none'} fix={a.fix or 'none'} brain={a.brain}")
    for t in result.transcript:
        print(f"  {t['role']:>8}: {t['text']}")
    print(f"outcome={result.outcome} order={result.order_id} turns={result.turns} "
          f"order_completed={order_completed(world, result)} violations={[v.invariant for v in violations]}")
    print(f"traces -> {a.out}")


if __name__ == "__main__":
    main()
