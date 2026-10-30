"""Split the organisers' labelled data into train / dev / holdout ONCE, with a fixed seed.

- train:   few-shot examples, fitting, prompt ideas. Look at it as much as you like.
- dev:     what you iterate against all weekend.
- holdout: touch only at milestones (e.g. 3-4 times total). This is your honest
           estimate of the judges' unseen test score. If dev goes up and holdout
           doesn't, you are overfitting.

Usage: python scripts/split_data.py data/raw.jsonl --dev 0.25 --holdout 0.2
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hack.data import load  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--dev", type=float, default=0.25)
    ap.add_argument("--holdout", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--stratify", action="store_true", help="keep label balance (classification)")
    ap.add_argument("--input-field", default="input")
    ap.add_argument("--expected-field", default="expected")
    ap.add_argument("--out", default="data")
    a = ap.parse_args()

    rows = load(a.path, a.input_field, a.expected_field)
    rng = random.Random(a.seed)
    groups: dict[str, list] = defaultdict(list)
    for r in rows:
        groups[str(r["expected"]) if a.stratify else "all"].append(r)

    splits = {"train": [], "dev": [], "holdout": []}
    for g in groups.values():
        rng.shuffle(g)
        n_hold, n_dev = round(len(g) * a.holdout), round(len(g) * a.dev)
        splits["holdout"] += g[:n_hold]
        splits["dev"] += g[n_hold:n_hold + n_dev]
        splits["train"] += g[n_hold + n_dev:]

    out = Path(a.out)
    out.mkdir(exist_ok=True)
    for name, items in splits.items():
        (out / f"{name}.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in items), encoding="utf-8")
        print(f"{name:8s} {len(items):5d} -> {out / name}.jsonl")


if __name__ == "__main__":
    main()
