"""Streamlit rendering helpers for the demo (brand colours, big fonts, chat bubbles, timeline cards, panels)."""
from __future__ import annotations

import html
from typing import Any

import streamlit as st

from demo_lib import AMBER, GREY, INK, NAVY, RED, TEAL, split_report

CSS = f"""
<style>
html, body, [class*="css"], .stMarkdown, .stText {{ font-size: 19px; }}
h1 {{ font-size: 2.6rem !important; letter-spacing: -0.5px; }}
h2 {{ font-size: 1.9rem !important; }}
h3 {{ font-size: 1.4rem !important; }}
.block-container {{ padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1800px; }}
[data-testid="stMetricValue"] {{ font-size: 2.2rem; color: {AMBER}; }}
[data-testid="stMetricLabel"] {{ font-size: 1rem; color: {GREY}; }}
.brand {{ color: {AMBER}; font-weight: 800; }}
.pill {{ display:inline-block; padding: 2px 12px; border-radius: 999px; font-size: 0.9rem; font-weight: 700; margin-right: 6px; }}
.pill-amber {{ background: {AMBER}; color: {NAVY}; }}
.pill-teal {{ background: {TEAL}; color: {NAVY}; }}
.pill-red {{ background: {RED}; color: white; }}
.pill-grey {{ background: #2A3F55; color: {INK}; }}
.wa {{ background: #0E2233; border-radius: 16px; padding: 14px; direction: rtl; }}
.wa.ltr {{ direction: ltr; }}
.bubble {{ max-width: 88%; padding: 10px 14px; border-radius: 14px; margin: 8px 0; font-size: 1.15rem; line-height: 1.5;
          box-shadow: 0 1px 2px rgba(0,0,0,.3); }}
.cust {{ background: #223B52; color: {INK}; margin-inline-end: auto; }}
.bot {{ background: #0F5F4F; color: {INK}; margin-inline-start: auto; }}
.bot.bad {{ border: 2px solid {AMBER}; }}
.bot.fixed {{ border: 2px solid {TEAL}; }}
.who {{ font-size: 0.8rem; color: {GREY}; margin-bottom: 2px; }}
.card {{ background: #12283D; border-left: 6px solid {GREY}; border-radius: 10px; padding: 10px 14px; margin: 8px 0; }}
.card .t {{ font-weight: 700; font-size: 1.05rem; }}
.card .b {{ color: #C9D6E2; font-size: 0.98rem; margin-top: 2px; }}
.card.amber {{ border-left-color: {AMBER}; }}
.card.teal {{ border-left-color: {TEAL}; }}
.card.red {{ border-left-color: {RED}; }}
.card.now {{ box-shadow: 0 0 0 2px {AMBER} inset; }}
.check {{ font-size: 1.1rem; padding: 6px 10px; border-radius: 8px; margin: 4px 0; background: #12283D; }}
.check.ok {{ border-left: 6px solid {TEAL}; }}
.check.bad {{ border-left: 6px solid {RED}; }}
.check.frozen {{ border-left: 6px solid {AMBER}; }}
.bar {{ height: 12px; background: #2A3F55; border-radius: 6px; overflow: hidden; margin: 4px 0 8px 0; }}
.bar > div {{ height: 100%; background: {AMBER}; }}
.bar.teal > div {{ background: {TEAL}; }}
.bar.red > div {{ background: {RED}; }}
.knob {{ font-family: ui-monospace, Menlo, monospace; font-size: 1.05rem; background: #0E2233; padding: 8px 12px; border-radius: 8px; margin: 6px 0; }}
.report {{ background: #12283D; border: 2px solid {AMBER}; border-radius: 14px; padding: 16px 20px; margin-top: 10px; }}
.report .ar {{ direction: rtl; font-size: 1.35rem; font-weight: 700; color: {AMBER}; }}
.report .en {{ font-size: 1.2rem; font-weight: 700; margin-top: 6px; }}
.report .sec {{ margin-top: 10px; color: #C9D6E2; }}
.caption {{ color: {GREY}; font-size: 0.95rem; }}
.big {{ font-size: 1.3rem; }}
footer {{ visibility: hidden; }}
</style>
"""


def setup(title: str) -> None:
    st.set_page_config(page_title=f"Najda · {title}", page_icon="🩺", layout="wide", initial_sidebar_state="expanded")
    st.markdown(CSS, unsafe_allow_html=True)


def header(title: str, subtitle: str = "") -> None:
    st.markdown(f"<h1><span class='brand'>نجدة Najda</span> · {html.escape(title)}</h1>", unsafe_allow_html=True)
    if subtitle:
        st.markdown(f"<div class='caption big'>{html.escape(subtitle)}</div>", unsafe_allow_html=True)


def pill(text: str, tone: str = "grey") -> str:
    return f"<span class='pill pill-{tone}'>{html.escape(text)}</span>"


def is_arabic(text: str) -> bool:
    return any("؀" <= ch <= "ۿ" for ch in text)


def chat(transcript: list[dict[str, str]], bad_bot: bool = False, fixed: bool = False, title: str = "") -> None:
    """WhatsApp-style transcript. bad_bot outlines the bot's wrong messages in amber, fixed outlines them in teal."""
    rtl = any(is_arabic(m["text"]) for m in transcript)
    parts = [f"<div class='wa {'rtl' if rtl else 'ltr'}'>"]
    if title:
        parts.append(f"<div class='who'>{html.escape(title)}</div>")
    for m in transcript:
        who = "customer" if m["role"] == "customer" else "bot"
        cls = "cust" if who == "customer" else "bot" + (" bad" if bad_bot else "") + (" fixed" if fixed else "")
        parts.append(f"<div class='bubble {cls}'><div class='who'>{'العميل · customer' if who == 'customer' else 'البوت · bot'}</div>"
                     f"{html.escape(m['text'])}</div>")
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def card(title: str, body: str = "", tone: str = "", now: bool = False) -> None:
    st.markdown(f"<div class='card {tone} {'now' if now else ''}'><div class='t'>{html.escape(title)}</div>"
                + (f"<div class='b'>{html.escape(body)}</div>" if body else "") + "</div>", unsafe_allow_html=True)


def conf_bar(label: str, conf: float, tone: str = "") -> None:
    st.markdown(f"<div style='display:flex;justify-content:space-between'><span>{html.escape(label)}</span>"
                f"<span style='color:{AMBER};font-weight:700'>{conf:.0%}</span></div>"
                f"<div class='bar {tone}'><div style='width:{conf * 100:.0f}%'></div></div>", unsafe_allow_html=True)


def event(ev: dict[str, Any], now: bool = False) -> None:
    """One timeline event."""
    k = ev["kind"]
    tone = {"baseline": "red", "money": "red", "freeze": "red", "escalate": "red", "patch": "amber", "guardrail": "amber",
            "hypotheses": "amber", "llm": "", "evidence": "", "bisect": "", "playbook": "", "triage": "", "turn": "",
            "playbook_hit": "teal", "learned": "teal"}.get(k, "")
    if k in ("replay", "canary", "regression", "verify"):
        tone = "teal" if ev.get("ok") else "red"
    if k == "guardrail":
        tone = "teal" if ev.get("allowed") else "red"
    if k == "decision":
        tone = "teal" if ev.get("status") == "recovered" else "amber"
    if k == "evidence":
        card(ev["title"], " · ".join(ev["chips"]), tone, now)
        return
    if k == "hypotheses":
        st.markdown(f"<div class='card amber {'now' if now else ''}'><div class='t'>Ranked hypotheses"
                    + (" · model recommends escalation" if ev.get("escalate") else "") + "</div>", unsafe_allow_html=True)
        for h in ev["ranked"]:
            status = h.get("status", "proposed")
            tone_h = "red" if status in ("ungrounded", "rejected", "blocked") else "teal" if status == "verified" else ""
            conf_bar(f"{h['label']}  ·  {status}" + (f"  ·  {h['note']}" if h.get("note") else ""), float(h.get("confidence", 0)), tone_h)
            st.markdown(f"<div class='b caption'>{html.escape(h.get('rationale', ''))}<br>evidence spans: "
                        f"{html.escape(', '.join(h.get('evidence', [])[:6]))} · patch: {html.escape(str(h.get('patch') or 'none'))}</div>",
                        unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        return
    card(ev["title"], ev.get("body", ""), tone, now)


def checklist(state: dict[str, Any]) -> None:
    rows = [state["served"]] + state["checklist"]
    for row in rows:
        if state["frozen"] and row["was_broken"] and not row["ok"]:
            cls, mark = "frozen", "⏸"
        elif row["ok"]:
            cls, mark = "ok", "✓"
        else:
            cls, mark = "bad", "✗"
        st.markdown(f"<div class='check {cls}'>{mark} {html.escape(row['label'])}</div>", unsafe_allow_html=True)


def config_diff(state: dict[str, Any]) -> None:
    if not state["diff"]:
        msg = "no config change" + (" (change freeze)" if state["frozen"] else "")
        st.markdown(f"<div class='knob' style='color:{GREY}'>{msg}</div>", unsafe_allow_html=True)
        return
    for d in state["diff"]:
        st.markdown(f"<div class='knob'>{html.escape(d['knob'])}: <span style='color:{RED}'>{html.escape(str(d['before']))}</span>"
                    f" → <span style='color:{TEAL}'>{html.escape(str(d['after']))}</span></div>", unsafe_allow_html=True)
    if state["rolled_back"]:
        st.markdown(f"<div class='caption' style='color:{AMBER}'>rolled back</div>", unsafe_allow_html=True)


def counters(state: dict[str, Any]) -> None:
    c1, c2, c3 = st.columns(3)
    c1.metric("LLM calls", state["llm_calls"])
    c2.metric("Cost", f"${state['cost']:.3f}")
    c3.metric("Time", f"{state['elapsed_s']:.1f}s")


def report_card(report: str) -> None:
    r = split_report(report)
    body = "".join(f"<div class='sec'><b>{html.escape(k)}:</b> {html.escape(r[k])}</div>"
                   for k in ("Summary", "Impact", "Recommended human action") if k in r)
    st.markdown(f"<div class='report'><div class='ar'>{html.escape(r['ar'])}</div><div class='en'>{html.escape(r['en'])}</div>{body}</div>",
                unsafe_allow_html=True)
