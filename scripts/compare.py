"""Regression check: compare two runs example by example.

Shows the score change AND which examples got fixed vs broken. A new version
that fixes 10 and breaks 8 is not the same as one that fixes 2 and breaks 0.

Usage:
  python scripts/compare.py <old_run_id> <new_run_id>
  python scripts/compare.py latest:baseline_majority latest:v2_fewshot
  python scripts/compare.py A B --fail-on-regression 0.01   # exit 1 if primary drops >1 point
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "experiments" / "runs"


def resolve(ref: str, split: str | None) -> Path:
    if ref.startswith("latest:"):
        system = ref.split(":", 1)[1]
        cands = []
        for d in RUNS.iterdir():
            s = json.loads((d / "summary.json").read_text())
            if s["system"] == system and s["perturbation"] == "none" and (split is None or s["split"] == split):
                cands.append((s["time_utc"], d))
        if not cands:
            sys.exit(f"No clean runs for system '{system}'")
        return max(cands)[1]
    return RUNS / ref


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--split", default="dev")
    ap.add_argument("--show", type=int, default=5, help="examples to print per bucket")
    ap.add_argument("--fail-on-regression", type=float, default=None)
    a = ap.parse_args()

    old_d, new_d = resolve(a.old, a.split), resolve(a.new, a.split)
    so, sn = (json.loads((d / "summary.json").read_text()) for d in (old_d, new_d))
    metric = sn["primary_metric"]
    po = {r["id"]: r for r in map(json.loads, (old_d / "predictions.jsonl").read_text().splitlines())}
    pn = {r["id"]: r for r in map(json.loads, (new_d / "predictions.jsonl").read_text().splitlines())}
    common = po.keys() & pn.keys()

    fixed = [i for i in common if pn[i]["scores"][metric] > po[i]["scores"][metric]]
    broken = [i for i in common if pn[i]["scores"][metric] < po[i]["scores"][metric]]
    delta = (sn["primary"] or 0) - (so["primary"] or 0)

    print(f"{metric}: {so['primary']} ({so['system']}) -> {sn['primary']} ({sn['system']})  delta={delta:+.4f}")
    print(f"examples: {len(common)} shared | fixed {len(fixed)} | broken {len(broken)}")
    for label, ids in (("FIXED", fixed), ("BROKEN", broken)):
        for i in sorted(ids)[: a.show]:
            print(f"\n[{label}] id={i}\n  expected: {str(pn[i]['expected'])[:200]}"
                  f"\n  old: {str(po[i]['pred'])[:200]}\n  new: {str(pn[i]['pred'])[:200]}")

    if a.fail_on_regression is not None and delta < -a.fail_on_regression:
        sys.exit(f"\nREGRESSION: {metric} dropped by {-delta:.4f}")


if __name__ == "__main__":
    main()
