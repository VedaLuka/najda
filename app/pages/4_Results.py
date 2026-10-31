from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ui  # noqa: E402
from demo_lib import section, table_rows  # noqa: E402

ui.setup("Results")
ui.header("Results", "every table below is generated from experiments/log.jsonl by scripts/report.py; nothing typed by hand")

st.markdown("""
<div class='caption big'>Primary metric = <b>outcome_correct</b>: a fixable incident counts only if it is recovered AND not
escalated; a must-escalate incident counts only if it is escalated with no config change beyond containment. 95% bootstrap
confidence intervals over incidents. Held-out families were never seen by the doctor code or prompts; the transfer set is a
second patient (Hajz, a restaurant booking bot) with zero fault-specific changes.</div>
""", unsafe_allow_html=True)

tab_conf, tab_final, tab_abl, tab_safe, tab_cost = st.tabs(
    ["Confirmation run (fresh seeds)", "Pre-registered final run", "Ablations", "Safety", "Haiku vs Sonnet"])

with tab_conf:
    st.markdown("### heldout-confirm · order bot · 25 incidents of the held-out families, new seeds")
    st.markdown(section("RESULTS.md", "heldout-confirm"))
    st.markdown("### transfer-confirm · Hajz · 15 incidents, new seeds")
    st.markdown(section("RESULTS.md", "transfer-confirm"))
    st.markdown("### Pre-registered hypotheses C1-C4 and the trade-off")
    st.markdown(section("RESULTS.md", "Hypotheses"))
    st.markdown(f"""
<div class='caption'>Honest reading: <b>najda_v6 is the ablation arm 'v5 minus diff_diagnosis'</b>, promoted to a version AFTER its
held-out score (0.84 vs 0.72) was seen, so the confirmation sets above are its first clean numbers. They were frozen (tag confirm-v1)
and the hypotheses written before any arm ran; results were reported as they came, no retries. At n = 25 the heldout-confirm CIs
overlap. <b>dropped_payment_webhook stays 0/4</b> for every Najda arm by design: the money-knob policy that gives
<span style='color:{ui.TEAL}'>0 dangerous actions on every set</span> also refuses the correct payment_verify fix during a payment
incident, which is why single_llm (no such policy) lands between v5 and v6 on this set.</div>
""", unsafe_allow_html=True)

with tab_final:
    st.markdown("### Held-out · order bot · 25 incidents (run Fri 30 Oct 21:31 KSA, code frozen at prereg-final)")
    st.markdown(section("PREREGISTRATION.md", "Held-out (order bot"))
    st.markdown("### Transfer · Hajz · 22 incidents, zero fault-specific changes")
    st.markdown(section("PREREGISTRATION.md", "Transfer (Hajz"))
    st.markdown("### Pre-registered hypotheses H1-H4")
    st.markdown(section("PREREGISTRATION.md", "Hypotheses", 0))
    st.markdown(f"""
<div class='caption'><b>H4 reversed.</b> We pre-registered that removing diff_diagnosis (grounding every hypothesis in spans that
differ between failing and passing chats) would hurt. It cost 3 held-out incidents instead: on arabic_numerals the only evidence is
the customer's own text, which the grounding rule discards. The arm without it became <b>najda_v6</b>, and the confirmation tab shows
the gain replicating on fresh seeds (+3 of 25 held-out, +4 of 15 transfer, nothing broken). Runbook (dev rules only) collapses to
0.12 on held-out families: hand-written rules do not transfer; the loop does.</div>
""", unsafe_allow_html=True)

with tab_abl:
    st.markdown("### Ablations on dev: najda_v4 minus one component at a time")
    st.markdown(section("RESULTS.md", "Ablations"))
    st.markdown("""
<div class='caption'>On dev families every component is redundant for accuracy (the loop already reaches 0.976); the components
earn their keep elsewhere: code rules stop churn on healthy and transient incidents, memory halves cost, the money policy gives zero
dangerous actions on the safety set, and diff_diagnosis turned out to be net negative on held-out families (removed in v6).</div>
""", unsafe_allow_html=True)
    with st.expander("Dev progression of every doctor (baselines first)"):
        st.markdown(section("RESULTS.md", "Progression (dev"))

with tab_safe:
    st.markdown("### Safety stress set: decoy logs, money at risk mixed with a fixable fault, innocent deploys in history")
    st.markdown(section("RESULTS.md", "Safety stress set"))
    st.markdown("### Robustness: noisy logs, dropped spans, weak evidence, Arabic-only and English-only")
    st.markdown(section("RESULTS.md", "Robustness set"))
    st.markdown("""
<div class='caption'>single_llm touches a decoy knob or changes config during a money incident on 4 of 13 temptations; Najda's one
dangerous action (same for v3, v4 and v4 without guardrails) is the money_plus_fixable case that motivated the v5 change freeze.
Zero dangerous actions on held-out, transfer and both confirmation sets after that change.</div>
""", unsafe_allow_html=True)

with tab_cost:
    rows = table_rows(section("RESULTS.md", "heldout-confirm"))
    sonnet = next((r for r in rows if r[0].startswith("najda_v6 COLD") and "Haiku" not in r[0]), None)
    haiku = next((r for r in rows if "Haiku" in r[0]), None)
    if sonnet and haiku:
        c1, c2 = st.columns(2)
        c1.metric("najda_v6 · Sonnet 5.5 investigator", f"outcome {sonnet[2].split(' ')[0].strip('*')}", f"${sonnet[8]} per incident")
        c2.metric("najda_v6 · Haiku 5.5 investigator", f"outcome {haiku[2].split(' ')[0].strip('*')}", f"${haiku[8]} per incident")
    st.markdown("### Model swap on dev (najda_v4)")
    st.markdown(section("RESULTS.md", "Model swap"))
    st.markdown("""
<div class='caption'>Haiku as the investigator is about 10x cheaper and loses the combo incidents (two faults stacked). Descriptive
only: Haiku arms were not pre-registered as hypotheses. Costs are real token counts priced from configs/prices.json; cache hits keep
the original usage so replays report what the run actually cost.</div>
""", unsafe_allow_html=True)
