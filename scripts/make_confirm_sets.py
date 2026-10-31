"""Build and freeze the step-7 CONFIRMATION sets (replication: same families as held-out / transfer, NEW seeds).

  data/incidents_confirm/heldout_confirm/            25 order-bot incidents, held-out families, seeds 6001..
  data/incidents_transfer_confirm/transfer_confirm/  15 Hajz incidents, transfer families, seeds 7001..

  python scripts/make_confirm_sets.py            # refuses to overwrite a frozen set
  python scripts/make_confirm_sets.py --verify   # recompute the SHA-256 manifests and compare

Each set gets MANIFEST.sha256 (every file, _truth included) on creation and is committed, tag `confirm-v1`,
before any doctor runs on it. Sanity allowed before the freeze: oracle 1.000 and do_nothing ~0, nothing else.
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
sys.path.insert(0, str(ROOT / "scripts"))

from hack.bench.incidents import heldout_confirm_plan, index_line, run_incident, save_bundle  # noqa: E402
from hack.hajz.bench import transfer_confirm_plan  # noqa: E402
from make_stress_sets import MANIFEST, manifest  # noqa: E402

SETS = {"heldout_confirm": (ROOT / "data" / "incidents_confirm", heldout_confirm_plan, "1.1", "order"),
        "transfer_confirm": (ROOT / "data" / "incidents_transfer_confirm", transfer_confirm_plan, "transfer-1", "hajz")}


def build(name: str) -> None:
    out, plan, version, patient = SETS[name]
    if (out / MANIFEST).exists():
        sys.exit(f"{out} is frozen ({MANIFEST} exists); refusing to rebuild")
    rows, fams = [], Counter()
    for spec in plan():
        run = run_incident(spec)
        rows.append(index_line(run, save_bundle(run, out).relative_to(out)) | {"patient": spec.patient})
        fams[spec.family] += 1
    with (out / name / "index.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out / "BENCH_VERSION").write_text(version + "\n")
    (out / "PATIENT").write_text(patient + "\n")
    text = manifest(out)
    (out / MANIFEST).write_text(text)
    failed, total = sum(r["chats_failed"] for r in rows), sum(r["n_chats"] for r in rows)
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    print(f"{name}: {len(rows)} incidents, {len(fams)} families, {failed}/{total} chats failing, "
          f"{len(text.splitlines())} files, manifest {digest} -> {out}")


def verify(name: str) -> bool:
    out = SETS[name][0]
    frozen = (out / MANIFEST).read_text()
    ok = frozen == manifest(out)
    print(f"{name}: {'byte-identical to frozen manifest' if ok else 'DIFFERS from frozen manifest'} "
          f"({hashlib.sha256(frozen.encode()).hexdigest()[:16]})")
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
