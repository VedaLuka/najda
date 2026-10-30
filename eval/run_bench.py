"""Score one doctor on IncidentBench, log the run, print a short summary.

  python eval/run_bench.py --doctor runbook --split dev --note "B1 baseline"
  python eval/run_bench.py --doctor single_llm --limit 3 --note "cost probe"
  python eval/run_bench.py --doctor najda_v1 --sequential --memory on

Writes experiments/runs/<run_id>/{results.jsonl,summary.json} and appends to experiments/log.jsonl.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hack.bench.harness import make_brain, treat_incident  # noqa: E402
from hack.bench.incidents import BENCH_VERSION_FILE  # noqa: E402
from hack.bench.score import PRIMARY_METRIC, aggregate, score_incident  # noqa: E402
from hack.bench.seal import truth_sealed  # noqa: E402
from hack.bench.truth import read_truth  # noqa: E402
from hack.doctors import get_doctor  # noqa: E402
from hack.llm import STATS, load_roles  # noqa: E402

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass


def git_info() -> dict:
    def run(*cmd):
        try:
            return subprocess.check_output(cmd, cwd=ROOT, stderr=subprocess.DEVNULL, text=True).strip()
        except Exception:
            return None
    return {"commit": run("git", "rev-parse", "--short", "HEAD"), "dirty": bool(run("git", "status", "--porcelain"))}


def bench_version(bench_dir: Path) -> str:
    path = bench_dir / BENCH_VERSION_FILE
    return path.read_text().strip() if path.exists() else "1.0"


def list_bundles(bench_dir: Path, split: str, limit: int | None) -> list[Path]:
    bundles = sorted(p for p in (bench_dir / split).iterdir() if p.is_dir())
    return bundles[:limit] if limit else bundles


def run_bench(doctor_name: str, split: str, bench_dir: Path, limit: int | None = None, sequential: bool = False,
              memory: bool = False, workers: int = 4, config: dict | None = None,
              replay_brain: str = "scripted") -> list[dict]:
    """Treat every incident, then score. Truth is preloaded, then sealed while doctors run."""
    bundles = list_bundles(bench_dir, split, limit)
    truths = {b.name: read_truth(b) for b in bundles}
    shared = get_doctor(doctor_name, config)

    def one(bundle: Path):
        doctor = shared if sequential else get_doctor(doctor_name, config)
        if sequential and not memory:
            doctor.reset_memory()
        return treat_incident(doctor, bundle, truths[bundle.name], replay_brain)

    with truth_sealed():
        if sequential:
            treated = [one(b) for b in bundles]
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                treated = list(pool.map(one, bundles))

    rows = []
    for bundle, (resolution, incident_config) in zip(bundles, treated):
        truth = truths[bundle.name]
        res = resolution.to_dict()
        rows.append({"incident_id": bundle.name, "family": truth["family"], "noisy": truth["noisy"],
                     "scores": score_incident(truth, res, incident_config, make_brain(replay_brain)),
                     "resolution": res})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--doctor", required=True)
    ap.add_argument("--split", default="dev", choices=["dev", "heldout"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--sequential", action="store_true", help="run incidents in fixed order, one doctor instance")
    ap.add_argument("--memory", default="off", choices=["on", "off"], help="keep doctor memory across incidents (needs --sequential)")
    ap.add_argument("--config", help="JSON config file for the doctor")
    ap.add_argument("--workers", type=int, default=int(os.getenv("EVAL_WORKERS", 4)))
    ap.add_argument("--bench-dir", default=str(ROOT / "data" / "incidents"))
    ap.add_argument("--replay-brain", default="scripted", choices=["scripted", "llm"],
                    help="patient brain for replays + scoring; 'llm' = milestone validation on a subset (costs money)")
    ap.add_argument("--note", default="")
    ap.add_argument("--no-log", action="store_true", help="smoke runs: print only, write nothing")
    a = ap.parse_args()
    if a.memory == "on" and not a.sequential:
        sys.exit("--memory on requires --sequential")
    if a.split == "heldout":
        print("!! HELDOUT run: milestones only. Never tune on these results. !!")

    config = json.loads(Path(a.config).read_text()) if a.config else {}
    t0 = time.time()
    replay_cost_before = STATS["cost_usd"] if a.replay_brain == "llm" else 0.0
    rows = run_bench(a.doctor, a.split, Path(a.bench_dir), a.limit, a.sequential, a.memory == "on", a.workers, config,
                     a.replay_brain)
    wall = time.time() - t0
    agg = aggregate(rows)

    run_id = f"{datetime.now().strftime('%m%d-%H%M%S')}_{a.doctor}_{a.split}"
    roles = load_roles()
    summary = {
        "kind": "bench", "run_id": run_id, "time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "system": a.doctor, "doctor": a.doctor, "split": a.split, "perturbation": "none", "n": agg["n"],
        "primary_metric": PRIMARY_METRIC, "primary": agg[PRIMARY_METRIC], "metrics": agg,
        "errors": sum(1 for r in rows if r["resolution"]["error"]), "wall_s": round(wall, 1),
        "mean_latency_s": agg["mean_wall_s"], "llm": {"calls": agg["llm_calls"], "cost_usd": agg["cost_usd"]},
        "models": roles, "sequential": a.sequential, "memory": a.memory, "limit": a.limit,
        "config_hash": hashlib.sha1(json.dumps(config, sort_keys=True).encode()).hexdigest()[:8], "config": config,
        "replay_llm_cost_usd": round(STATS["cost_usd"] - replay_cost_before, 4) if a.replay_brain == "llm" else 0.0,
        "replay_brain": a.replay_brain, "bench": Path(a.bench_dir).name, "bench_version": bench_version(Path(a.bench_dir)),
        "git": git_info(), "note": a.note,
    }
    m = agg
    print(f"{run_id}: outcome={m['outcome_correct']:.3f} recovered={m['recovered']:.3f} rc@1={m['root_cause_top1']:.3f} "
          f"esc_ok={m['escalation_correct']:.3f} dangerous={m['dangerous']:.3f} n={m['n']} "
          f"cost=${m['cost_usd']:.4f} llm_calls={m['llm_calls']} errors={summary['errors']} wall={wall:.1f}s")
    if a.no_log:
        return
    run_dir = ROOT / "experiments" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "results.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    with (ROOT / "experiments" / "log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({k: v for k, v in summary.items() if k != "config"}, ensure_ascii=False, default=str) + "\n")
    print(f"details -> {run_dir.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
