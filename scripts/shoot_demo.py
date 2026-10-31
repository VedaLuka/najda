"""Screenshot every screen of the static console (app/web/) at 1920x1080 with Playwright + Chromium.

  python scripts/shoot_demo.py [--out docs/screenshots] [--port 8765]

Serves app/ on a local http.server (so /web/ and /data/ share an origin), waits for each screen's data-ready flag,
and writes PNGs. Fails loudly on any console error. Dev-only: needs `pip install playwright && playwright install chromium`.
"""
from __future__ import annotations

import argparse
import contextlib
import functools
import http.server
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOTS = [
    ("live_001_01_reads", "live?inc=heldout_confirm-001&k=3&video=1"),
    ("live_001_02_hypothesis", "live?inc=heldout_confirm-001&k=9&video=1"),
    ("live_001_03_canary", "live?inc=heldout_confirm-001&k=14&video=1"),
    ("live_001_04_recovered", "live?inc=heldout_confirm-001&k=99&video=1"),
    ("live_004_v5_escalated", "live?inc=heldout_confirm-004&doctor=najda_v5&k=99&video=1"),
    ("live_004_v6_recovered", "live?inc=heldout_confirm-004&doctor=najda_v6&k=99&video=1"),
    ("learn", "learn?video=1"),
    ("stop_hajz", "stop?inc=transfer_confirm-011&video=1"),
    ("stop_webhook", "stop?inc=heldout_confirm-010&video=1"),
    ("results", "results?video=1"),
]


@contextlib.contextmanager
def serve(directory: Path, port: int):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a: object) -> None:
            pass

    handler = functools.partial(Quiet, directory=str(directory))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        srv.shutdown()


def shoot(out: Path, port: int, only: list[str] | None = None) -> list[Path]:
    from playwright.sync_api import sync_playwright

    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    errors: list[str] = []
    with serve(ROOT / "app", port) as base, sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        for name, route in SHOTS:
            if only and name not in only:
                continue
            page.goto(f"{base}/web/#{route}")
            page.wait_for_selector("section.screen[data-ready='1']", timeout=10_000)
            page.wait_for_timeout(1300)  # let the entrance animations and count-ups settle
            path = out / f"{name}.png"
            page.screenshot(path=str(path))
            written.append(path)
            print(f"wrote {path}")
        browser.close()
    if errors:
        raise SystemExit("console errors:\n" + "\n".join(errors))
    return written


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/screenshots")
    ap.add_argument("--port", type=int, default=8771)
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    shoot(ROOT / a.out, a.port, a.only)
