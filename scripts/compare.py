"""Regression check between two runs, incident by incident (bench) or example by example (legacy).

  python scripts/compare.py latest:runbook latest:single_llm
  python scripts/compare.py <old_run_id> <new_run_id> --fail-on-regression 0.01
Shows the primary-metric change AND which incidents got fixed vs broken.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "experiments" / "runs"


def resolve(ref: str, split: str) -> Path:
    if not ref.startswith("latest:"):
        return RUNS / ref
    name = ref.split(":", 1)[1]
    cands = []
    for d in RUNS.iterdir():
        s = json.loads((d / "summary.json").read_text())
        if s["system"] == name and s.get("perturbation", "none") == "none" and s["split"] == split and not s.get("limit") \
                and s.get("bench", "incidents") == "incidents" and s.get("replay_brain", "scripted") == "scripted":
            cands.append((s["time_utc"], d.name, d))
    if not cands:
        sys.exit(f"No full {split} runs for '{name}'")
    return max(cands)[2]


def load_rows(run: Path) -> tuple[dict[str, dict], str]:
    if (run / "results.jsonl").exists():
        rows = [json.loads(l) for l in (run / "results.jsonl").read_text().splitlines()]
        return {r["incident_id"]: r for r in rows}, "bench"
    rows = [json.loads(l) for l in (run / "predictions.jsonl").read_text().splitlines()]
    return {r["id"]: r for r in rows}, "legacy"


def describe(row: dict) -> str:
    s, res = row["scores"], row["resolution"]
    causes = ",".join(c["label"] for c in res["root_causes"][:2]) or "-"
    return (f"recovered={s['recovered']} escalated={res['escalated']} causes={causes} "
            f"changed={s['changed_knobs'] or '-'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--split", default="dev")
    ap.add_argument("--show", type=int, default=5, help="incidents to print per bucket")
    ap.add_argument("--fail-on-regression", type=float, default=None)
    a = ap.parse_args()

    old_d, new_d = resolve(a.old, a.split), resolve(a.new, a.split)
    so, sn = (json.loads((d / "summary.json").read_text()) for d in (old_d, new_d))
    metric = sn["primary_metric"]
    po, kind = load_rows(old_d)
    pn, _ = load_rows(new_d)
    common = sorted(po.keys() & pn.keys())
    fixed = [i for i in common if pn[i]["scores"][metric] > po[i]["scores"][metric]]
    broken = [i for i in common if pn[i]["scores"][metric] < po[i]["scores"][metric]]
    delta = (sn["primary"] or 0) - (so["primary"] or 0)

    print(f"{metric}: {so['primary']} ({so['system']}) -> {sn['primary']} ({sn['system']})  delta={delta:+.4f}")
    print(f"shared: {len(common)} | fixed {len(fixed)} | broken {len(broken)}")
    for label, ids in (("FIXED", fixed), ("BROKEN", broken)):
        for i in ids[: a.show]:
            if kind == "bench":
                print(f"[{label}] {i} ({pn[i]['family']})\n  old: {describe(po[i])}\n  new: {describe(pn[i])}")
            else:
                print(f"[{label}] {i}\n  expected: {str(pn[i]['expected'])[:200]}\n  old: {str(po[i]['pred'])[:200]}"
                      f"\n  new: {str(pn[i]['pred'])[:200]}")
    if a.fail_on_regression is not None and delta < -a.fail_on_regression:
        sys.exit(f"REGRESSION: {metric} dropped by {-delta:.4f}")


if __name__ == "__main__":
    main()
