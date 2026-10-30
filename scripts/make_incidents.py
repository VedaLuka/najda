"""Build IncidentBench: data/incidents/{dev,heldout}/<id>/ bundles + data/incidents/_truth/.

  python scripts/make_incidents.py                   # rebuild dev only (heldout is frozen)
  python scripts/make_incidents.py --small --out data/_smoke --rebuild-heldout
Heldout is never overwritten unless --rebuild-heldout is given: it must stay byte-identical.
Files are overwritten in place (no delete + recreate): synced folders such as iCloud Desktop
turn delete-then-recreate into "name 2.json" conflict copies.
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

from hack.bench.incidents import BENCH_VERSION, BENCH_VERSION_FILE, bench_plan, index_line, run_incident, save_bundle  # noqa: E402


def remove_stale(out: Path, split: str, keep: set[str]) -> None:
    """Delete bundles and truth files from earlier plans that are no longer generated."""
    for bundle in (out / split).iterdir():
        if bundle.is_dir() and bundle.name not in keep:
            shutil.rmtree(bundle)
    for truth in (out / "_truth" / split).glob("*.json"):
        if truth.stem not in keep:
            truth.unlink()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data" / "incidents"))
    ap.add_argument("--small", action="store_true", help="one incident per kind (smoke)")
    ap.add_argument("--rebuild-heldout", action="store_true", help="also regenerate heldout (breaks comparability!)")
    a = ap.parse_args()
    out = Path(a.out)
    splits = ["dev", "heldout"] if a.rebuild_heldout or not (out / "heldout").exists() else ["dev"]

    lines: dict[str, list[dict]] = {s: [] for s in splits}
    families: dict[str, Counter] = {s: Counter() for s in ("dev", "heldout")}
    for spec in bench_plan(small=a.small):
        families[spec.split][spec.family] += 1
        if spec.split not in splits:
            continue
        run = run_incident(spec)
        lines[spec.split].append(index_line(run, save_bundle(run, out).relative_to(out)))
    for split in splits:
        remove_stale(out, split, {r["incident_id"] for r in lines[split]})
    for split, rows in lines.items():
        with (out / split / "index.jsonl").open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        failed, total = sum(r["chats_failed"] for r in rows), sum(r["n_chats"] for r in rows)
        print(f"{split}: {len(rows)} incidents, {len(families[split])} families, {failed}/{total} chats failing -> {out / split}")
    if "heldout" not in splits:
        print("heldout: untouched (frozen)")
    (out / BENCH_VERSION_FILE).write_text(BENCH_VERSION + "\n")
    overlap = set(families["dev"]) & set(families["heldout"]) - {"healthy"}
    print("family overlap between splits:", sorted(overlap) or "none")


if __name__ == "__main__":
    main()
