"""The stepped incident view shared by the 'Live incident' and 'Knows when to stop' pages."""
from __future__ import annotations

import html
import time
from typing import Any

import streamlit as st

import ui
from demo_lib import build_timeline, failing_chats, incident, manifest, panel_state

AUTOPLAY_S = 1.5


def pick_incident(role: str, key: str) -> dict[str, Any]:
    options = [m for m in manifest()["incidents"] if m["role"] == role]
    labels = {m["id"]: f"{m['headline']}  ·  {m['family']}  ·  {m['id']}" for m in options}
    chosen = st.selectbox("Incident", [m["id"] for m in options], format_func=lambda i: labels[i], key=f"{key}_incident")
    return incident(chosen)


def pick_doctor(inc: dict[str, Any], key: str) -> str:
    doctors = list(inc["trajectories"])
    if len(doctors) == 1:
        return doctors[0]
    names = {"najda_v6": "najda_v6 (final)", "najda_v5": "najda_v5 (with diff_diagnosis grounding)"}
    st.markdown("<div class='caption'>v5 vs v6: the pre-registered H4 said removing diff_diagnosis would hurt. It did the "
                "opposite: v5 rejects the correct fix as ungrounded because the only evidence is the customer's text.</div>",
                unsafe_allow_html=True)
    return st.radio("Doctor", doctors, format_func=lambda d: names.get(d, d), horizontal=True, key=f"{key}_doctor",
                    index=doctors.index("najda_v6") if "najda_v6" in doctors else 0)


def stepper(n: int, key: str) -> int:
    """Next-step button, autoplay toggle, reset; returns how many events to show."""
    sk = f"{key}_step"
    st.session_state.setdefault(sk, 0)
    c1, c2, c3, c4 = st.columns([1.2, 1.4, 1, 3])
    if c1.button("Next step ▶", key=f"{key}_next", width='stretch', type="primary"):
        st.session_state[sk] = min(n, st.session_state[sk] + 1)
    auto = c2.toggle(f"Autoplay ({AUTOPLAY_S:.1f}s/step)", key=f"{key}_auto")
    if c3.button("Reset", key=f"{key}_reset", width='stretch'):
        st.session_state[sk] = 0
    if c4.button("Show all", key=f"{key}_all", width='stretch'):
        st.session_state[sk] = n
    k = st.session_state[sk]
    st.progress(k / n if n else 0.0, text=f"step {k} / {n}")
    return k


def autoplay_tick(n: int, key: str) -> None:
    sk = f"{key}_step"
    if st.session_state.get(f"{key}_auto") and st.session_state[sk] < n:
        time.sleep(AUTOPLAY_S)
        st.session_state[sk] += 1
        st.rerun()


def render(inc: dict[str, Any], doctor: str, key: str) -> None:
    traj = inc["trajectories"][doctor]
    events = build_timeline(traj["steps"])
    scores = traj["recorded"]["scores"]
    st.markdown(
        ui.pill(inc["family"], "amber") + ui.pill(f"patient: {inc['patient']}", "grey") + ui.pill(doctor, "grey")
        + ui.pill(f"recorded run {traj['recorded']['run_id']}", "grey")
        + (ui.pill("scored: outcome correct", "teal") if scores["outcome_correct"] else ui.pill("scored: miss", "red")),
        unsafe_allow_html=True)
    st.markdown(f"<div class='big'><b>{html.escape(inc['headline'])}</b> · <span dir='rtl'>{html.escape(inc['headline_ar'])}</span></div>"
                f"<div class='caption'>{html.escape(inc['silent'])}</div>", unsafe_allow_html=True)
    k = stepper(len(events), key)
    state = panel_state(inc, events, k, traj)

    left, mid, right = st.columns([1.1, 1.5, 1.1], gap="large")
    with left:
        st.subheader("What the customer saw")
        bad = failing_chats(inc)
        chat_id = st.selectbox("Chat", [c["chat_id"] for c in bad], key=f"{key}_chat")
        before = next(c for c in bad if c["chat_id"] == chat_id)
        after = {c["chat_id"]: c for c in inc.get("after_fix", {}).get(doctor, [])}
        if state["verified"] and chat_id in after:
            ui.chat(after[chat_id]["transcript"], fixed=True, title=f"{chat_id} · after Najda's fix (replayed)")
            with st.expander("before the fix"):
                ui.chat(before["transcript"], bad_bot=True, title=f"{chat_id} · incident")
        else:
            ui.chat(before["transcript"], bad_bot=True, title=f"{chat_id} · incident · outcome: {before['outcome']}")
        viol = [v for v in inc["bundle"]["invariants"] if v["chat_id"] == chat_id]
        for v in viol[:3]:
            st.markdown(f"<div class='caption' style='color:{ui.AMBER}'>invariant {html.escape(v['invariant'])}: {html.escape(v['detail'])}</div>",
                        unsafe_allow_html=True)
    with mid:
        st.subheader("Najda's timeline")
        if k == 0:
            st.markdown("<div class='caption'>Press Next step or switch on Autoplay.</div>", unsafe_allow_html=True)
        for i, ev in enumerate(events[:k]):
            ui.event(ev, now=(i == k - 1))
    with right:
        st.subheader("Business rules")
        ui.checklist(state)
        st.subheader("Config change")
        ui.config_diff(state)
        st.subheader("Budget")
        ui.counters(state)
        if state["done"] and traj.get("report"):
            st.subheader("Report card")
            ui.report_card(traj["report"])
    autoplay_tick(len(events), key)
