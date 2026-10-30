"""Build and freeze the TRANSFER split: ~22 incidents of the unseen patient Hajz (restaurant reservations).

  python scripts/make_transfer_set.py            # refuses to overwrite a frozen set
  python scripts/make_transfer_set.py --verify   # recompute the SHA-256 manifest and compare

data/incidents_transfer/transfer/<id>/ holds the bundles Najda sees; data/incidents_transfer/_truth/ the ground
truth it never reads. MANIFEST.sha256 covers every file (truth included) and is committed, with the tag
`transfer-v1`, before any doctor runs on the set.
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

from hack.bench.incidents import index_line, run_incident, save_bundle  # noqa: E402
from hack.hajz.bench import transfer_plan  # noqa: E402
from make_stress_sets import MANIFEST, manifest  # noqa: E402

OUT = ROOT / "data" / "incidents_transfer"
VERSION = "transfer-1"


def build() -> None:
    if (OUT / MANIFEST).exists():
        sys.exit(f"{OUT} is frozen ({MANIFEST} exists); refusing to rebuild")
    rows, fams = [], Counter()
    for spec in transfer_plan():
        run = run_incident(spec)
        rows.append(index_line(run, save_bundle(run, OUT).relative_to(OUT)) | {"patient": spec.patient})
        fams[spec.family] += 1
    with (OUT / "transfer" / "index.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (OUT / "BENCH_VERSION").write_text(VERSION + "\n")
    (OUT / "PATIENT").write_text("hajz\n")
    text = manifest(OUT)
    (OUT / MANIFEST).write_text(text)
    failed, total = sum(r["chats_failed"] for r in rows), sum(r["n_chats"] for r in rows)
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    print(f"transfer: {len(rows)} incidents, {len(fams)} families, {failed}/{total} chats failing, "
          f"{len(text.splitlines())} files, manifest {digest} -> {OUT}")


def verify() -> bool:
    frozen = (OUT / MANIFEST).read_text()
    ok = frozen == manifest(OUT)
    print(f"transfer: {'byte-identical to frozen manifest' if ok else 'DIFFERS from frozen manifest'} "
          f"({hashlib.sha256(frozen.encode()).hexdigest()[:16]})")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    if a.verify:
        sys.exit(0 if verify() else 1)
    build()


if __name__ == "__main__":
    main()
