"""The demo pack under app/data/ is complete and self-consistent, and the Streamlit pages render without exceptions.
Pack checks need no Streamlit; the render checks are skipped when Streamlit is not installed (make smoke stays key-free
and dependency-light)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import demo_lib as d  # noqa: E402

PAGES = ["Home.py", "pages/1_Live_incident.py", "pages/2_Learns_and_gets_cheaper.py", "pages/3_Knows_when_to_stop.py",
         "pages/4_Results.py"]


def test_manifest_lists_every_incident_file():
    m = d.manifest()
    ids = {i["id"] for i in m["incidents"]}
    assert {p.stem for p in (d.DATA / "incidents").glob("*.json")} == ids
    assert {i["role"] for i in m["incidents"]} == {"live", "escalate"}
    assert m["repeat"]["incidents"][0] != m["repeat"]["incidents"][1]


@pytest.mark.parametrize("meta", d.manifest()["incidents"], ids=lambda m: m["id"])
def test_incident_pack_is_replay_only_and_consistent(meta):
    inc = d.incident(meta["id"])
    assert inc["bundle"]["chats"] and inc["bundle"]["config"]["current"]
    assert set(inc["trajectories"]) == set(meta["doctors"])
    for doctor, traj in inc["trajectories"].items():
        llm = [s for s in traj["steps"] if s["action"] == "llm"]
        assert all(s["result"]["cached"] for s in llm), f"{meta['id']} {doctor}: an LLM step was not a cache hit"
        assert len(llm) == traj["llm_calls"]
        events = d.build_timeline(traj["steps"])
        kinds = [e["kind"] for e in events]
        assert kinds[0] == "baseline" and "hypotheses" in kinds and "decision" in kinds
        state = d.panel_state(inc, events, len(events), traj)
        assert state["done"] and state["llm_calls"] == traj["llm_calls"]
        assert abs(state["cost"] - traj["cost_usd"]) < 1e-5
        if traj["escalated"]:
            assert state["escalated"] and not state["diff"]
            assert d.split_report(traj["report"])["ar"] and d.split_report(traj["report"])["en"]
        else:
            assert state["verified"] and state["diff"]
            assert doctor in inc["after_fix"] and inc["after_fix"][doctor]
    assert d.failing_chats(inc)


def test_v5_vs_v6_story_is_in_the_pack():
    inc = d.incident("heldout_confirm-004")
    v5 = d.build_timeline(inc["trajectories"]["najda_v5"]["steps"])
    v6 = d.build_timeline(inc["trajectories"]["najda_v6"]["steps"])
    v5_status = {h["status"] for e in v5 if e["kind"] == "hypotheses" for h in e["ranked"]}
    assert v5_status == {"ungrounded"} and inc["trajectories"]["najda_v5"]["escalated"]
    assert any(e["kind"] == "verify" and e["ok"] for e in v6)
    assert inc["trajectories"]["najda_v6"]["final_config"]["normalize_numerals"] is True


def test_repeat_run_two_is_a_free_playbook_hit():
    rep = d.repeat()
    run1, run2 = rep["runs"]
    assert run1["llm_calls"] > 0 and run2["llm_calls"] == 0 and run2["cost_usd"] == 0.0
    assert [e["event"] for e in run2["playbook_events"]][:2] == ["match", "hit"]
    assert any(e["kind"] == "verify" and e["ok"] for e in d.build_timeline(run2["steps"]))
    assert rep["playbooks"] and rep["playbooks"][0]["kind"] == "fix"


def test_results_sections_present():
    for heading in ("heldout-confirm", "transfer-confirm", "Hypotheses", "Ablations", "Safety stress set", "Model swap"):
        assert d.section("RESULTS.md", heading), heading
    assert d.section("PREREGISTRATION.md", "Held-out (order bot") and d.section("PREREGISTRATION.md", "Transfer (Hajz")
    rows = d.table_rows(d.section("RESULTS.md", "heldout-confirm"))
    assert any(r[0].startswith("najda_v6 COLD") for r in rows) and any("Haiku" in r[0] for r in rows)
    assert d.read_csv("learning_curve_streams.csv") and d.read_csv("learning_curve.csv")


@pytest.mark.parametrize("page", PAGES)
def test_pages_render_without_exceptions(page):
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "app" / page), default_timeout=60).run()
    assert not at.exception, [str(e) for e in at.exception]


def test_live_page_steps_to_the_end():
    pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "app" / "pages/1_Live_incident.py"), default_timeout=60).run()
    at.button(key="live_heldout_confirm-001_najda_v6_all").click().run()
    assert not at.exception
    assert any("Report card" in h.value for h in at.subheader)
