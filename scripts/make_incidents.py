"""Build IncidentBench: data/incidents/{dev,heldout}/<id>/ bundles + data/incidents/_truth/.

  python scripts/make_incidents.py                 # full bench (~37 dev, ~25 heldout)
  python scripts/make_incidents.py --small --out data/_smoke
Prints one summary line per split; details are in <out>/<split>/index.jsonl.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hack.bench.incidents import bench_plan, index_line, run_incident, save_bundle  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data" / "incidents"))
    ap.add_argument("--small", action="store_true", help="one incident per kind (smoke)")
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)

    lines: dict[str, list[dict]] = {"dev": [], "heldout": []}
    families: dict[str, Counter] = {"dev": Counter(), "heldout": Counter()}
    for spec in bench_plan(small=a.small):
        run = run_incident(spec)
        bundle = save_bundle(run, out)
        lines[spec.split].append(index_line(run, bundle))
        families[spec.split][spec.family] += 1
    for split, rows in lines.items():
        with (out / split / "index.jsonl").open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        failed = sum(r["chats_failed"] for r in rows)
        total = sum(r["n_chats"] for r in rows)
        print(f"{split}: {len(rows)} incidents, {len(families[split])} families, "
              f"{failed}/{total} chats failing -> {out / split}")
    overlap = set(families["dev"]) & set(families["heldout"]) - {"healthy"}
    print("family overlap between splits:", sorted(overlap) or "none")


if __name__ == "__main__":
    main()
