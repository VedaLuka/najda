"""Learning-curve experiment: does Najda get cheaper as it learns, without getting less accurate?

  python scripts/learning_curve.py --doctor najda_v4_nt --seeds 1 2 3

Streams every dev incident through one doctor instance (sequential), memory OFF once and memory ON once per
seed (seeded shuffle of the stream). Every arm is a normal logged bench run. Writes
experiments/learning_curve/<ts>/{curve.csv,summary.md,summary.json}.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import statistics
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "experiments" / "runs"


def bench(doctor: str, memory: str, seed: int, note: str, memory_in: str | None = None) -> Path:
    cmd = [sys.executable, str(ROOT / "eval" / "run_bench.py"), "--doctor", doctor, "--split", "dev", "--sequential",
           "--memory", memory, "--order-seed", str(seed), "--note", note]
    if memory_in:
        cmd += ["--memory-in", memory_in]
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=True).stdout
    print(out.strip().splitlines()[0])
    m = re.search(r"details -> (experiments/runs/\S+)", out)
    assert m, out
    return ROOT / m.group(1)


def rows_of(run: Path, arm: str, seed: int) -> list[dict]:
    rows = []
    cum = 0.0
    costs: list[float] = []
    for r in map(json.loads, (run / "results.jsonl").read_text().splitlines()):
        res = r["resolution"]
        cum += res["cost_usd"]
        costs.append(res["cost_usd"])
        rows.append({"arm": arm, "seed": seed, "run_id": run.name, "position": r["position"], "incident_id": r["incident_id"],
                     "family": r["family"], "cost_usd": res["cost_usd"], "llm_calls": res["llm_calls"],
                     "outcome_correct": int(r["scores"]["outcome_correct"]), "escalated": int(res["escalated"]),
                     "playbook_event": r["memory"]["outcome"], "tier": r["memory"]["tier"] or "",
                     "learned": int(r["memory"]["learned"]), "cum_cost_usd": round(cum, 4),
                     "ma5_cost_usd": round(statistics.mean(costs[-5:]), 4)})
    return rows


def bootstrap_ci(values_by_incident: dict[str, list[float]], n: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """Mean over incidents of the per-incident mean (a seed-pooled incident counts once), 95% CI over incidents."""
    ids = sorted(values_by_incident)
    per = [statistics.mean(values_by_incident[i]) for i in ids]
    rng = random.Random(seed)
    means = sorted(statistics.mean(rng.choices(per, k=len(per))) for _ in range(n))
    return statistics.mean(per), means[int(0.025 * n)], means[int(0.975 * n) - 1]


def summarise(rows: list[dict]) -> dict:
    out = {}
    for arm in ("off", "on"):
        rs = [r for r in rows if r["arm"] == arm]
        by_inc: dict[str, list[float]] = {}
        cost_inc: dict[str, list[float]] = {}
        for r in rs:
            by_inc.setdefault(r["incident_id"], []).append(r["outcome_correct"])
            cost_inc.setdefault(r["incident_id"], []).append(r["cost_usd"])
        acc, lo, hi = bootstrap_ci(by_inc)
        cost, clo, chi = bootstrap_ci(cost_inc)
        n_seeds = len({r["seed"] for r in rs})
        half = max(r["position"] for r in rs) // 2
        first = [r["cost_usd"] for r in rs if r["position"] <= half]
        second = [r["cost_usd"] for r in rs if r["position"] > half]
        hits = sum(r["playbook_event"] in ("hit", "hit_escalate") for r in rs)
        esc_hits = sum(r["playbook_event"] == "hit_escalate" for r in rs)
        false = sum(r["playbook_event"] == "false_match" for r in rs)
        partial = sum(r["playbook_event"] == "partial" for r in rs)
        out[arm] = {"seeds": n_seeds, "n_rows": len(rs), "accuracy": round(acc, 4), "accuracy_ci": [round(lo, 4), round(hi, 4)],
                    "cost_per_incident": round(cost, 4), "cost_ci": [round(clo, 4), round(chi, 4)],
                    "total_cost_per_stream": round(sum(r["cost_usd"] for r in rs) / n_seeds, 4),
                    "llm_calls_per_stream": round(sum(r["llm_calls"] for r in rs) / n_seeds, 1),
                    "cost_first_half": round(statistics.mean(first), 4), "cost_second_half": round(statistics.mean(second), 4),
                    "playbook_hits": hits, "escalate_fast_hits": esc_hits, "partial_hits": partial, "false_matches": false,
                    "hit_rate": round(hits / len(rs), 3), "false_match_rate": round(false / max(hits + false, 1), 3),
                    "zero_llm_incidents": sum(r["llm_calls"] == 0 for r in rs)}
    return out


def write_md(summary: dict, out: Path, doctor: str, run_ids: dict) -> None:
    lines = [f"# Learning curve: `{doctor}` on dev (memory OFF vs ON)", "",
             "| arm | seeds | accuracy [95% CI] | $/incident [95% CI] | $/stream | LLM calls/stream | $ first half | $ second half | hits | esc-fast hits | partial hits | false matches | hit rate | false-match rate | zero-LLM incidents |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for arm, s in summary.items():
        lines.append(f"| {arm} | {s['seeds']} | {s['accuracy']:.3f} [{s['accuracy_ci'][0]:.3f}, {s['accuracy_ci'][1]:.3f}] | "
                     f"{s['cost_per_incident']:.4f} [{s['cost_ci'][0]:.4f}, {s['cost_ci'][1]:.4f}] | {s['total_cost_per_stream']:.3f} | "
                     f"{s['llm_calls_per_stream']} | {s['cost_first_half']:.4f} | {s['cost_second_half']:.4f} | {s['playbook_hits']} | "
                     f"{s['escalate_fast_hits']} | {s['partial_hits']} | {s['false_matches']} | {s['hit_rate']:.2f} | {s['false_match_rate']:.2f} | {s['zero_llm_incidents']} |")
    lines += ["", "Runs: " + ", ".join(f"{k}={v}" for k, v in run_ids.items()), "",
              "Escalate-fast hits are counted apart: an escalation cannot be verified by replay. A partial hit = the "
              "playbook's patch was kept as a verified improvement but the incident had a second fault (investigated normally)."]
    (out / "summary.md").write_text("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--doctor", default="najda_v4_nt")
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    ap.add_argument("--off-seed", type=int, default=1)
    ap.add_argument("--memory-in", help="optional store to start the ON arms from")
    a = ap.parse_args()
    ts = datetime.now().strftime("%m%d-%H%M%S")
    out = ROOT / "experiments" / "learning_curve" / f"{ts}_{a.doctor}"
    out.mkdir(parents=True)
    rows: list[dict] = []
    run_ids = {}
    run = bench(a.doctor, "off", a.off_seed, f"learning curve: memory OFF, stream seed {a.off_seed}")
    run_ids["off"] = run.name
    rows += rows_of(run, "off", a.off_seed)
    for seed in a.seeds:
        run = bench(a.doctor, "on", seed, f"learning curve: memory ON, stream seed {seed}", a.memory_in)
        run_ids[f"on_seed{seed}"] = run.name
        rows += rows_of(run, "on", seed)
    with (out / "curve.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    summary = summarise(rows)
    (out / "summary.json").write_text(json.dumps({"doctor": a.doctor, "runs": run_ids, "summary": summary}, indent=2))
    write_md(summary, out, a.doctor, run_ids)
    print((out / "summary.md").read_text())
    print(f"data -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
