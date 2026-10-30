"""Load examples as a list of {"id", "input", "expected"} dicts from .jsonl, .json or .csv.

If the challenge data uses other column names, map them with --input-field / --expected-field
or set them in the config: {"data": {"input_field": "question", "expected_field": "label"}}.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path


def load(path: str | Path, input_field: str = "input", expected_field: str = "expected",
         id_field: str = "id") -> list[dict]:
    path = Path(path)
    if path.suffix == ".jsonl":
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    elif path.suffix == ".json":
        rows = json.loads(path.read_text(encoding="utf-8"))
    elif path.suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
    else:
        raise ValueError(f"Unsupported data format: {path.suffix}")

    out = []
    for i, r in enumerate(rows):
        if input_field == "*":
            x = {k: v for k, v in r.items() if k not in (expected_field, id_field)}
        else:
            x = r[input_field]
        out.append({"id": str(r.get(id_field, i)), "input": x, "expected": r.get(expected_field)})
    return out
