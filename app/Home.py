"""Najda demo dashboard: replay-only, reads app/data/ (built by scripts/export_demo_pack.py), no API key.

  make demo   # == streamlit run app/Home.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ui  # noqa: E402
from demo_lib import manifest, section  # noqa: E402

ui.setup("Home")
ui.header("an AI agent that fixes other AI agents", "and gets cheaper every time it learns a fix")

m = manifest()
c1, c2, c3 = st.columns(3)
c1.metric("held-out outcome, najda_v6", "0.84", help="25 unseen-family incidents, confirmation set, CI [0.68, 0.96]")
c2.metric("transfer outcome (Hajz), najda_v6", "1.00", help="15 fresh Hajz incidents, confirmation set, CI degenerate at 15/15")
c3.metric("dangerous actions, every set", "0")

st.markdown("""
### What you are looking at
A WhatsApp order bot (Arabic, English, Saudi dialect) over stock, order and payment services breaks in ways that
produce **no error**: prices arrive in halalas, customers type Arabic-Indic digits, stock is stale. **Najda** reads only
the incident bundle (traces, metrics, config history, transcripts, business-rule violations), investigates with a big
model, proposes the smallest patch, passes it through guardrails and a canary, verifies it by replaying the failed chats,
and either keeps the fix or hands over with a bilingual report. A verified fix becomes a **playbook**: the next time
the same signature appears, no model call is needed.

Pages, in the order of the video:

1. **Live incident** — a silent fault on the order bot, stepped or on autoplay.
2. **Learns and gets cheaper** — the same fault twice: full investigation, then a $0 playbook hit; the learning curve.
3. **Knows when to stop** — a payment provider outage: change freeze, no patch, report.
4. **Results** — held-out, transfer and confirmation tables with confidence intervals; ablations; safety; honest captions.
""")

st.markdown(f"<div class='caption'>Everything is replayed from recorded runs. Pack built at {m['generated']} from commit "
            f"{m['commit']}; incidents {', '.join(i['id'] for i in m['incidents'])}. Zero live API calls.</div>",
            unsafe_allow_html=True)

with st.expander("How the numbers were produced"):
    st.markdown(section("PREREGISTRATION.md", "What this does and does not show"))
