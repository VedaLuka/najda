"""New API spend, read from the LLM cache: every entry created after `--since` was a real API call.

  python scripts/spend.py --since "2026-10-30 20:59" [--budget 8] [--planned 5.5]

Cache hits never create entries, so this is the money actually spent, unlike experiments/log.jsonl, which
prices cache hits at their original cost. `--planned` is the estimate for the arms still to run; the script
exits 1 when spent + planned exceeds the budget, so a driver can stop before the next arm.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hack.llm import CACHE_DIR, cost_of  # noqa: E402


def spend_since(since: datetime) -> tuple[float, int, dict[str, float]]:
    total, n, by_model = 0.0, 0, {}
    for p in (ROOT / CACHE_DIR).glob("*.json"):
        if datetime.fromtimestamp(p.stat().st_mtime) < since:
            continue
        entry = json.loads(p.read_text())
        model = entry["payload"]["model"]
        usd, _ = cost_of(model, entry.get("usage", {}))
        total += usd
        n += 1
        by_model[model] = by_model.get(model, 0.0) + usd
    return total, n, by_model


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True, help="local time 'YYYY-MM-DD HH:MM'")
    ap.add_argument("--budget", type=float, default=8.0)
    ap.add_argument("--planned", type=float, default=0.0, help="estimated cost of the arms still to run")
    a = ap.parse_args()
    since = datetime.strptime(a.since, "%Y-%m-%d %H:%M")
    total, n, by_model = spend_since(since)
    projected = total + a.planned
    print(f"spent since {a.since}: ${total:.3f} over {n} API calls "
          + " ".join(f"{m}=${c:.3f}" for m, c in sorted(by_model.items())))
    print(f"projected (spent + planned ${a.planned:.2f}): ${projected:.2f} of budget ${a.budget:.2f}")
    if projected > a.budget:
        print("OVER BUDGET: stop and ask before the next arm")
        sys.exit(1)


if __name__ == "__main__":
    main()
