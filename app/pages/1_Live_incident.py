from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import live  # noqa: E402
import ui  # noqa: E402

ui.setup("Live incident")
ui.header("Live incident", "a silent fault: no error in the logs, only business rules broken")
inc = live.pick_incident("live", "live")
doctor = live.pick_doctor(inc, f"live_{inc['id']}")
live.render(inc, doctor, f"live_{inc['id']}_{doctor}")
