from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import live  # noqa: E402
import ui  # noqa: E402

ui.setup("Knows when to stop")
ui.header("Knows when to stop", "money is moving and the upstream is down: freeze, no patch, hand over")
st.markdown("""
<div class='caption big'>When a payment or deposit upstream fails, Najda enters a <b>change freeze</b>: no config knob
may move until a human looks, because a wrong fix during a money incident is worse than a slow one. The second incident
shows the price of that policy: the right fix exists, Najda names it, and refuses to apply it. It is scored as a miss and
reported as such.</div>
""", unsafe_allow_html=True)
inc = live.pick_incident("escalate", "stop")
doctor = live.pick_doctor(inc, f"stop_{inc['id']}")
live.render(inc, doctor, f"stop_{inc['id']}_{doctor}")
