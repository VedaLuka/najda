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
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hack.bench.harness import treat_incident  # noqa: E402
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


def list_bundles(bench_dir: Path, split: str, limit: int | None, ids: list[str] | None = None) -> list[Path]:
    bundles = sorted(p for p in (bench_dir / split).iterdir() if p.is_dir())
    if ids:
        missing = set(ids) - {b.name for b in bundles}
        if missing:
            sys.exit(f"unknown incident ids: {sorted(missing)}")
        bundles = [b for b in bundles if b.name in set(ids)]
    return bundles[:limit] if limit else bundles


def run_bench(doctor_name: str, split: str, bench_dir: Path, limit: int | None = None, sequential: bool = False,
              memory: bool = False, workers: int = 4, config: dict | None = None,
              replay_brain: str = "scripted", memory_in: Path | None = None, order_seed: int | None = None,
              memory_out: Path | None = None, ids: list[str] | None = None) -> list[dict]:
    """Treat every incident, then score. Truth is preloaded, then sealed while doctors run.
    Sequential runs may start from a saved memory store (memory_in), stream incidents in a seeded shuffle
    (order_seed) and save the store they end with (memory_out)."""
    bundles = list_bundles(bench_dir, split, limit, ids)
    if order_seed is not None:
        random.Random(order_seed).shuffle(bundles)
    truths = {b.name: read_truth(b) for b in bundles}
    shared = get_doctor(doctor_name, config)
    if memory_in is not None:
        shared.load_memory(memory_in)

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

    if memory_out is not None and hasattr(shared, "save_memory"):
        shared.save_memory(memory_out)
    rows = []
    for position, (bundle, (resolution, incident_config)) in enumerate(zip(bundles, treated)):
        truth = truths[bundle.name]
        res = resolution.to_dict()
        rows.append({"incident_id": bundle.name, "family": truth["family"], "noisy": truth["noisy"], "position": position,
                     "conditions": truth.get("conditions", {}), "modifiers": truth.get("modifiers", []),
                     "scores": score_incident(truth, res, incident_config, replay_brain),
                     "memory": memory_events(res), "resolution": res})
    return rows


def memory_events(res: dict) -> dict:
    """Playbook events of one incident (hit / false_match / miss / learned ...), for the learning curve."""
    ev = [s["result"] for s in res["steps"] if s["action"] == "najda.playbook"]
    outcome = next((e["event"] for e in ev if e["event"] in ("hit", "hit_escalate", "partial", "false_match")), "miss" if ev else "n/a")
    match = next((e for e in ev if e["event"] == "match"), {})
    return {"outcome": outcome, "tier": match.get("tier"), "playbook": match.get("id"),
            "learned": any(e["event"] == "learned" for e in ev)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--doctor", required=True)
    ap.add_argument("--split", default="dev", help="dev | heldout | a stress-set split such as safety / robust")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--ids", help="comma-separated incident ids to run (subset runs are probes, like --limit)")
    ap.add_argument("--models", help="alternate configs/models.json for this run (model swap)")
    ap.add_argument("--sequential", action="store_true", help="run incidents in fixed order, one doctor instance")
    ap.add_argument("--memory", default="off", choices=["on", "off"], help="keep doctor memory across incidents (needs --sequential)")
    ap.add_argument("--config", help="JSON config file for the doctor")
    ap.add_argument("--memory-in", help="start from a saved playbook store (needs --sequential --memory on)")
    ap.add_argument("--order-seed", type=int, help="shuffle the incident stream with this seed (needs --sequential)")
    ap.add_argument("--workers", type=int, default=int(os.getenv("EVAL_WORKERS", 4)))
    ap.add_argument("--bench-dir", default=str(ROOT / "data" / "incidents"))
    ap.add_argument("--replay-brain", default="scripted", choices=["scripted", "llm"],
                    help="patient brain for replays + scoring; 'llm' = milestone validation on a subset (costs money)")
    ap.add_argument("--note", default="")
    ap.add_argument("--no-log", action="store_true", help="smoke runs: print only, write nothing")
    a = ap.parse_args()
    if a.memory == "on" and not a.sequential:
        sys.exit("--memory on requires --sequential")
    if (a.memory_in or a.order_seed is not None) and not a.sequential:
        sys.exit("--memory-in / --order-seed require --sequential")
    if a.split == "heldout":
        print("!! HELDOUT run: milestones only. Never tune on these results. !!")

    if a.models:
        os.environ["NAJDA_MODELS"] = str(Path(a.models).resolve())
    ids = [x for x in a.ids.split(",") if x] if a.ids else None
    config = json.loads(Path(a.config).read_text()) if a.config else {}
    t0 = time.time()
    replay_cost_before = STATS["cost_usd"] if a.replay_brain == "llm" else 0.0
    run_id = f"{datetime.now().strftime('%m%d-%H%M%S')}_{a.doctor}_{a.split}"
    memory_out = None if a.no_log or a.memory != "on" else ROOT / "experiments" / "runs" / run_id / "playbooks.json"
    rows = run_bench(a.doctor, a.split, Path(a.bench_dir), a.limit, a.sequential, a.memory == "on", a.workers, config,
                     a.replay_brain, Path(a.memory_in) if a.memory_in else None, a.order_seed, memory_out, ids)
    wall = time.time() - t0
    agg = aggregate(rows)

    run_dir = ROOT / "experiments" / "runs" / run_id
    roles = load_roles()
    summary = {
        "kind": "bench", "run_id": run_id, "time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "system": a.doctor, "doctor": a.doctor, "split": a.split, "perturbation": "none", "n": agg["n"],
        "primary_metric": PRIMARY_METRIC, "primary": agg[PRIMARY_METRIC], "metrics": agg,
        "errors": sum(1 for r in rows if r["resolution"]["error"]), "wall_s": round(wall, 1),
        "mean_latency_s": agg["mean_wall_s"], "llm": {"calls": agg["llm_calls"], "cost_usd": agg["cost_usd"]},
        "models": roles, "sequential": a.sequential, "memory": a.memory, "limit": a.limit or (len(ids) if ids else None),
        "ids": ids, "models_file": a.models,
        "memory_in": a.memory_in, "order_seed": a.order_seed,
        "playbooks": {k: sum(1 for r in rows if r["memory"]["outcome"] == k) for k in ("hit", "hit_escalate", "partial", "false_match", "miss")},
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
