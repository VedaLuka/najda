"""The static console (app/web/) is self-contained: every data path it fetches exists, nothing loads from the network,
and (when Playwright is installed) the page renders the live incident from the demo pack without console errors."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "app" / "web"
DATA = ROOT / "app" / "data"
sys.path.insert(0, str(ROOT / "scripts"))


def _sources() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in [WEB / "index.html", *WEB.glob("css/*.css"), *WEB.glob("js/*.js")]}


def test_no_runtime_network_dependency() -> None:
    for name, text in _sources().items():
        assert not re.search(r"https?://(?!127\.0\.0\.1|localhost|www\.w3\.org)", text), f"{name} loads something from the network"
    fonts_css = (WEB / "vendor/fonts/fonts.css").read_text(encoding="utf-8")
    for f in re.findall(r"url\(([^)]+)\)", fonts_css):
        assert (WEB / "vendor/fonts" / f).is_file(), f"font {f} is not vendored"
    assert all(fam in fonts_css for fam in ("IBM Plex Sans", "IBM Plex Sans Arabic", "JetBrains Mono"))


def test_every_fetched_pack_file_exists() -> None:
    js = "\n".join(_sources().values())
    assert "data-root" in js and 'content="../data"' in (WEB / "index.html").read_text(encoding="utf-8")
    for rel in ("manifest.json", "repeat.json", "results/sections.json"):
        assert (DATA / rel).is_file(), rel
    for name in re.findall(r"csv\('([^']+)'\)", js):
        assert (DATA / "results" / name).is_file(), name
    import json
    man = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    for m in man["incidents"]:
        assert (DATA / "incidents" / f"{m['id']}.json").is_file()


def test_shoot_script_routes_cover_every_screen() -> None:
    from shoot_demo import SHOTS
    screens = {route.split("?")[0] for _, route in SHOTS}
    assert screens == {"live", "learn", "stop", "results"}


@pytest.mark.skipif(pytest.importorskip("playwright", reason="playwright not installed") is None, reason="no playwright")
def test_console_renders_the_live_incident(tmp_path: Path) -> None:
    from playwright.sync_api import sync_playwright
    from shoot_demo import serve

    errors: list[str] = []
    with serve(ROOT / "app", 8779) as base, sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as e:  # noqa: BLE001 - chromium not installed on this machine
            pytest.skip(f"chromium not available: {e}")
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{base}/web/#live?inc=heldout_confirm-001&k=99")
        page.wait_for_selector("section.screen[data-ready='1']", timeout=10_000)
        assert page.locator(".ev").count() >= 10
        assert page.locator(".ev.verify").count() == 1
        assert "ريال" in page.locator(".phone-body").inner_text()
        assert page.locator(".status-track .st.now").inner_text() == "RECOVERED"
        assert page.locator(".diff .add").inner_text().startswith("+ price_unit")
        for route in ("learn", "stop", "results"):
            page.goto(f"{base}/web/#{route}")
            page.wait_for_selector("section.screen[data-ready='1']", timeout=10_000)
            if route != "stop":
                page.wait_for_selector(".chart svg", timeout=10_000)
        assert page.locator(".chart svg").count() >= 4
        browser.close()
    assert errors == []
