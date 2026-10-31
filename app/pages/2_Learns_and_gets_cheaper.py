from __future__ import annotations

import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ui  # noqa: E402
from demo_lib import AMBER, TEAL, build_timeline, read_csv, repeat  # noqa: E402

ui.setup("Learns and gets cheaper")
ui.header("Learns and gets cheaper", "the same fault twice: investigate once, then replay the playbook for $0")

rep = repeat()
run1, run2 = rep["runs"]
st.markdown(f"<div class='caption big'>Doctor <b>{rep['doctor']}</b> meets <b>{run1['family']}</b> on {run1['incident_id']}, then a "
            f"sibling incident {run2['incident_id']} (different menu items, different customers). A playbook is a structured "
            f"signature of the failing spans plus a patch template: no free text, no ids, matched before any model call, and "
            f"applied through the same guardrails, canary and replay.</div>", unsafe_allow_html=True)

c1, c2 = st.columns(2, gap="large")
for col, run, label in ((c1, run1, "Run 1 · cold: full investigation"), (c2, run2, "Run 2 · playbook hit")):
    with col:
        st.subheader(label)
        m1, m2, m3 = st.columns(3)
        m1.metric("LLM calls", run["llm_calls"])
        m2.metric("Cost", f"${run['cost_usd']:.4f}")
        m3.metric("Doctor steps", len(run["steps"]))
        events = [e for e in build_timeline(run["steps"]) if e["kind"] != "evidence"]
        for ev in events:
            ui.event(ev)
saved = run1["cost_usd"] - run2["cost_usd"]
st.markdown(f"<div class='big'>Saved <b style='color:{TEAL}'>${saved:.4f} ({saved / run1['cost_usd']:.0%})</b> and "
            f"<b style='color:{TEAL}'>{run1['llm_calls'] - run2['llm_calls']} LLM calls</b> on the second incident, with the same "
            f"verification: canary, full replay of the failed chats, regression replay of the passing ones.</div>", unsafe_allow_html=True)

with st.expander("The playbook that was learned (exactly what is stored)"):
    st.json(rep["playbooks"])

st.subheader("Learning curve: memory ON vs OFF over a 42-incident stream (dev)")
rows = pd.DataFrame(read_csv("learning_curve_streams.csv"))
rows = rows[rows["doctor"] == "najda_v4"].copy()
for c in ("position", "ma5_cost_usd", "cum_cost_usd", "cost_usd", "llm_calls"):
    rows[c] = pd.to_numeric(rows[c])
rows["memory"] = rows["arm"].map({"off": "memory OFF", "on": "memory ON (mean of 3 orders)"})
curve = rows.groupby(["memory", "position"], as_index=False)[["ma5_cost_usd", "cum_cost_usd"]].mean()
scale = alt.Scale(domain=["memory OFF", "memory ON (mean of 3 orders)"], range=[AMBER, TEAL])
base = alt.Chart(curve).encode(x=alt.X("position:Q", title="incident number in the stream"),
                               color=alt.Color("memory:N", scale=scale, legend=alt.Legend(title=None, orient="top", labelFontSize=16)))
left, right = st.columns(2)
left.altair_chart(base.mark_line(strokeWidth=4).encode(
    y=alt.Y("ma5_cost_usd:Q", title="cost per incident, 5-incident moving average ($)")).properties(height=360), width='stretch')
right.altair_chart(base.mark_line(strokeWidth=4).encode(
    y=alt.Y("cum_cost_usd:Q", title="cumulative cost ($)")).properties(height=360), width='stretch')

summary = pd.DataFrame(read_csv("learning_curve.csv"))
summary = summary[summary["doctor"] == "najda_v4"][["memory", "seeds", "accuracy", "ci_lo", "ci_hi", "cost_per_incident",
                                                      "llm_calls_per_stream", "hit_rate", "zero_llm_incidents"]]
st.dataframe(summary, hide_index=True, width='stretch')
st.markdown("""
<div class='caption'>Measured on the dev split with najda_v4 (Sonnet 5.5 investigator, Haiku triage), memory OFF = one stream,
memory ON = three shuffled streams; v5 and v6 carry the same playbook code unchanged. Accuracy 0.976 → 0.968 (the loss is on
combo_schema_rate, two faults stacked, where a partial playbook hit fixed the first fault and the second was missed), cost per incident $0.025 → $0.015, 45% of incidents
hit a playbook, 63 of 126 incidents needed zero LLM calls, no false match. On the fresh held-out set the ONLINE arm was 45% cheaper
per incident and lost one incident the same way (pre-registered H3: cheaper, not strictly at no loss).</div>
""", unsafe_allow_html=True)
