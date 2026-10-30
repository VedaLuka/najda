"""Ground-truth files live OUTSIDE the incident bundles under data/incidents/_truth/.
Only the generator, replay and tests import this module. Najda never does."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def truth_path(incident_dir: Path) -> Path:
    split, incident_id = incident_dir.parent.name, incident_dir.name
    return incident_dir.parent.parent / "_truth" / split / f"{incident_id}.json"


def write_truth(incident_dir: Path, truth: dict[str, Any]) -> Path:
    path = truth_path(incident_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(truth, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def read_truth(incident_dir: Path) -> dict[str, Any]:
    return json.loads(truth_path(incident_dir).read_text(encoding="utf-8"))
