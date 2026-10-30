"""Estimate the API cost of the pre-registered final run from logged dev costs per incident.

  python scripts/estimate_cost.py [--factor 1.4]

Per-incident cost of each arm = its latest full dev run / 42 (cache hits are priced at the original cost, so
these are real per-incident prices). Unseen splits need more investigation rounds than dev, so every arm is
multiplied by `--factor` (default 1.4) for the pessimistic figure.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "experiments" / "log.jsonl"

HELDOUT_N, TRANSFER_N = 25, 22
# arm -> (doctor whose dev run prices it, extra summary filters)
PRICED_BY = {
    "single_llm": ("single_llm", {}),
    "najda_v5 COLD": ("najda_v5", {"memory": "off"}),
    "najda_v5 ONLINE": ("najda_v4", {"memory": "on"}),  # v5 has no memory-on dev run; v4's learning curve prices it
    "v5 minus diff_diagnosis": ("najda_v4_no_diffdiag", {}),
    "v5 minus bisect": ("najda_v4_no_bisect", {}),
    "v5 COLD, Haiku big model": ("najda_v4", {"models_file": "configs/models_haiku_big.json"}),
}
HELDOUT_ARMS = ["do_nothing", "restart", "runbook", "single_llm", "najda_v5 COLD", "najda_v5 ONLINE",
                "v5 minus diff_diagnosis", "v5 minus bisect", "v5 COLD, Haiku big model"]
TRANSFER_ARMS = ["do_nothing", "restart", "runbook", "single_llm", "najda_v5 COLD", "v5 COLD, Haiku big model"]


def per_incident(rows: list[dict], doctor: str, where: dict) -> float:
    hits = [r for r in rows if r["doctor"] == doctor and r["split"] == "dev" and not r.get("limit")
            and r.get("bench", "incidents") == "incidents" and r.get("replay_brain", "scripted") == "scripted"
            and all((r.get(k) or ("off" if k == "memory" else None)) == v for k, v in where.items())]
    if not hits:
        raise SystemExit(f"no dev run prices {doctor} {where}")
    latest = max(hits, key=lambda r: r["time_utc"])
    return latest["llm"]["cost_usd"] / latest["n"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--factor", type=float, default=1.4)
    a = ap.parse_args()
    rows = [json.loads(l) for l in LOG.read_text().splitlines() if l.strip()]
    rows = [r for r in rows if r.get("kind") == "bench"]
    lines, total = [], 0.0
    for split, arms, n in (("heldout", HELDOUT_ARMS, HELDOUT_N), ("transfer", TRANSFER_ARMS, TRANSFER_N)):
        for arm in arms:
            if arm not in PRICED_BY:
                lines.append(f"| {split} | {arm} | {n} | 0.0000 | 0.00 | 0.00 |")
                continue
            doctor, where = PRICED_BY[arm]
            p = per_incident(rows, doctor, where)
            lines.append(f"| {split} | {arm} | {n} | {p:.4f} | {p * n:.2f} | {p * n * a.factor:.2f} |")
            total += p * n
    print("| split | arm | n | $/incident (dev) | estimate $ | pessimistic $ (x%.1f) |" % a.factor)
    print("|---|---|---|---|---|---|")
    print("\n".join(lines))
    print(f"\nTOTAL estimate ${total:.2f}, pessimistic ${total * a.factor:.2f} "
          f"(hard cap: Najda stops at $0.40 per incident, single_llm is one call)")


if __name__ == "__main__":
    main()
