"""Build and freeze the step-5 stress sets (DEV families only, new seeds):

  data/incidents_safety/safety/   ~13 incidents that tempt a dangerous action
  data/incidents_robust/robust/   36 incidents = 6 dev faults x 6 harder conditions

  python scripts/make_stress_sets.py            # refuses to overwrite a frozen set
  python scripts/make_stress_sets.py --verify   # recompute the SHA-256 manifests and compare

Each set gets MANIFEST.sha256 (every file, including _truth) on creation; it is committed before any
doctor runs on the set, and --verify proves the set is byte-identical to the frozen one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hack.bench.incidents import index_line, robustness_plan, run_incident, safety_plan, save_bundle  # noqa: E402

SETS = {"safety": (ROOT / "data" / "incidents_safety", safety_plan),
        "robust": (ROOT / "data" / "incidents_robust", robustness_plan)}
MANIFEST = "MANIFEST.sha256"


def manifest(out: Path) -> str:
    lines = []
    for path in sorted(p for p in out.rglob("*") if p.is_file() and p.name != MANIFEST):
        lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(out)}")
    return "\n".join(lines) + "\n"


def build(name: str) -> None:
    out, plan = SETS[name]
    if (out / MANIFEST).exists():
        sys.exit(f"{out} is frozen ({MANIFEST} exists); refusing to rebuild")
    rows, fams = [], Counter()
    for spec in plan():
        run = run_incident(spec)
        rows.append(index_line(run, save_bundle(run, out).relative_to(out)) | {"conditions": spec.conditions,
                                                                                 "modifiers": spec.modifiers})
        fams[spec.family] += 1
    with (out / name / "index.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out / "BENCH_VERSION").write_text("1.1\n")
    text = manifest(out)
    (out / MANIFEST).write_text(text)
    failed, total = sum(r["chats_failed"] for r in rows), sum(r["n_chats"] for r in rows)
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    print(f"{name}: {len(rows)} incidents, {len(fams)} families, {failed}/{total} chats failing, "
          f"{len(text.splitlines())} files, manifest {digest} -> {out}")


def verify(name: str) -> bool:
    out, _ = SETS[name]
    frozen = (out / MANIFEST).read_text()
    ok = frozen == manifest(out)
    print(f"{name}: {'byte-identical to frozen manifest' if ok else 'DIFFERS from frozen manifest'}")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=list(SETS), action="append", help="default: both")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    names = a.set or list(SETS)
    if a.verify:
        sys.exit(0 if all(verify(n) for n in names) else 1)
    for n in names:
        build(n)


if __name__ == "__main__":
    main()
