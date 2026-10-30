"""Run one system on one split, score it, and log everything.

Every run writes:
  experiments/runs/<run_id>/predictions.jsonl   per-example inputs, preds, scores, errors
  experiments/runs/<run_id>/summary.json        metrics + full config + git commit
  experiments/log.jsonl                         one line per run (the master results table)

Examples:
  python eval/run_eval.py --system baseline_majority --split dev --note "floor"
  python eval/run_eval.py --system llm_zero_shot --config configs/zero_shot.json --split dev
  python eval/run_eval.py --system v2_fewshot --split dev --perturb typos
  python eval/run_eval.py --system v2_fewshot --split dev --robustness   # all perturbations
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hack import metrics as M  # noqa: E402
from hack import perturb  # noqa: E402
from hack.data import load  # noqa: E402
from hack.llm import STATS, reset_stats  # noqa: E402
from hack.systems import get_system  # noqa: E402

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
    return {"commit": run("git", "rev-parse", "--short", "HEAD"),
            "dirty": bool(run("git", "status", "--porcelain"))}


def evaluate(system_name: str, config: dict, split: str, perturbation: str, limit: int | None,
             workers: int, seed: int, note: str, data_dir: Path) -> dict:
    dcfg = config.get("data", {})
    fields = dict(input_field=dcfg.get("input_field", "input"),
                  expected_field=dcfg.get("expected_field", "expected"))
    examples = load(data_dir / f"{split}.jsonl", **fields)
    if limit:
        examples = examples[:limit]
    train_path = data_dir / "train.jsonl"
    train = load(train_path, **fields) if train_path.exists() else []

    system = get_system(system_name, config)
    system.fit(train)
    reset_stats()

    def one(i_ex):
        i, ex = i_ex
        x = perturb.apply(perturbation, ex["input"], seed, i)
        t0 = time.time()
        try:
            pred, err = system.predict(x), None
        except Exception as e:  # a crash on one example must not kill the run
            pred, err = None, f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=2)}"
        row = {"id": ex["id"], "input": x, "expected": ex["expected"], "pred": pred,
               "latency_s": round(time.time() - t0, 3), "error": err}
        row["scores"] = {m: (fn(pred, ex["expected"]) if err is None else 0.0)
                         for m, fn in M.EXAMPLE_METRICS.items()}
        return row

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(one, enumerate(examples)))
    wall = time.time() - t0

    n = len(rows)
    agg = {m: round(sum(r["scores"][m] for r in rows) / n, 4) if n else 0.0 for m in M.EXAMPLE_METRICS}
    for m, fn in M.CORPUS_METRICS.items():
        agg[m] = round(fn([r["pred"] for r in rows], [r["expected"] for r in rows]), 4)

    run_id = f"{datetime.now().strftime('%m%d-%H%M%S')}_{system_name}_{split}" + (
        f"_{perturbation}" if perturbation not in (None, "", "none") else "")
    cfg_hash = hashlib.sha1(json.dumps(config, sort_keys=True).encode()).hexdigest()[:8]
    summary = {
        "run_id": run_id, "time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "system": system_name, "split": split, "perturbation": perturbation or "none",
        "n": n, "primary_metric": M.PRIMARY_METRIC, "primary": agg.get(M.PRIMARY_METRIC),
        "metrics": agg, "errors": sum(r["error"] is not None for r in rows),
        "wall_s": round(wall, 1), "mean_latency_s": round(sum(r["latency_s"] for r in rows) / max(n, 1), 3),
        "llm": dict(STATS), "seed": seed, "config_hash": cfg_hash, "config": config,
        "git": git_info(), "note": note,
    }

    run_dir = ROOT / "experiments" / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "predictions.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    with (ROOT / "experiments" / "log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({k: v for k, v in summary.items() if k != "config"}, ensure_ascii=False,
                           default=str) + "\n")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", required=True)
    ap.add_argument("--config", help="JSON config file for the system")
    ap.add_argument("--split", default="dev", choices=["train", "dev", "holdout"])
    ap.add_argument("--perturb", default="none", choices=["none", *perturb.PERTURBATIONS])
    ap.add_argument("--robustness", action="store_true", help="run clean + every perturbation")
    ap.add_argument("--limit", type=int, help="first N examples only (quick smoke test)")
    ap.add_argument("--workers", type=int, default=int(os.getenv("EVAL_WORKERS", 8)))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument("--note", default="", help="what changed and why (goes in the log)")
    a = ap.parse_args()

    if a.split == "holdout":
        print("!! HOLDOUT run. Only do this at milestones. !!")
    config = json.loads(Path(a.config).read_text()) if a.config else {}
    perts = ["none", *perturb.PERTURBATIONS] if a.robustness else [a.perturb]

    for p in perts:
        s = evaluate(a.system, config, a.split, p, a.limit, a.workers, a.seed, a.note, Path(a.data_dir))
        print(f"{s['run_id']}: {s['primary_metric']}={s['primary']}  n={s['n']}  "
              f"errors={s['errors']}  wall={s['wall_s']}s  llm_calls={s['llm']['calls']} "
              f"(cached {s['llm']['cache_hits']})")


if __name__ == "__main__":
    main()
