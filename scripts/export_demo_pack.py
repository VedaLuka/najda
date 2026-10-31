"""Build the self-contained demo pack under app/data/ for the Streamlit dashboard (replay-only, no API key).

  python scripts/export_demo_pack.py            # writes app/data/ (fails if any LLM call is not in the disk cache)

Bench runs keep only the final resolution, so the step-level trajectories are regenerated here by rerunning the
selected incidents through the SAME doctor code with the LLM disk cache (.cache/llm): every call must be a cache
hit, so the pack costs $0 and is byte-reproducible. The pack also copies the chats, config, invariants and the
result tables (docs/RESULTS.md, docs/PREREGISTRATION.md, experiments/figures, learning curves) so the deployed app
reads nothing outside app/data/.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hack.bench.harness import treat_incident  # noqa: E402
from hack.bench.incidents import rerun  # noqa: E402
from hack.bench.seal import truth_sealed  # noqa: E402
from hack.bench.truth import read_truth  # noqa: E402
from hack.doctors import get_doctor  # noqa: E402
from hack.patient.config import ControlPanel  # noqa: E402
from hack.patients import DEFAULT_PATIENT, get_patient  # noqa: E402

OUT = ROOT / "app" / "data"

# Incidents shown in the app: bundle dir, recorded bench run per doctor (for family + scores), headline.
# Only frozen confirmation-set incidents (tag confirm-v1): nothing here was ever tuned on.
SELECTION: list[dict[str, Any]] = [
    {"id": "heldout_confirm-001", "bench": "incidents_confirm/heldout_confirm", "role": "live",
     "runs": {"najda_v6": "1031-030851_najda_v6_heldout_confirm"},
     "headline": "Prices arrive in halalas, the bot charges riyals",
     "headline_ar": "الأسعار بالهللات والبوت يحاسب بالريال",
     "silent": "No error, no failed chat: every order was created, paid and confirmed at 100x the menu price."},
    {"id": "heldout_confirm-004", "bench": "incidents_confirm/heldout_confirm", "role": "live",
     "runs": {"najda_v6": "1031-030851_najda_v6_heldout_confirm", "najda_v5": "1031-030553_najda_v5_heldout_confirm"},
     "headline": "Customers type ٤, the bot orders 1",
     "headline_ar": "العميل يكتب ٤ والبوت يطلب ١",
     "silent": "No error: Arabic-Indic digits are skipped, so every order is created and charged for quantity 1."},
    {"id": "transfer_confirm-011", "bench": "incidents_transfer_confirm/transfer_confirm", "role": "escalate",
     "runs": {"najda_v6": "1031-031520_najda_v6_transfer_confirm"},
     "headline": "Deposit provider down (Hajz booking bot)",
     "headline_ar": "مزوّد العربون متوقف (بوت حجز)",
     "silent": "Every deposit charge returns 503. No config knob can fix a provider outage; the right move is to freeze and hand over."},
    {"id": "heldout_confirm-010", "bench": "incidents_confirm/heldout_confirm", "role": "escalate",
     "runs": {"najda_v6": "1031-030851_najda_v6_heldout_confirm"},
     "headline": "Payment webhook never arrives (the price of the policy)",
     "headline_ar": "إشعار الدفع لا يصل (ثمن سياسة الأمان)",
     "silent": "Charges succeed but the webhook stays pending. Najda finds the right fix and refuses it: no payment knob moves while payments are failing. Scored as a miss."},
]
REPEAT = {"doctor": "najda_v6", "first": "heldout_confirm-001", "second": "heldout_confirm-002",
          "bench": "incidents_confirm/heldout_confirm", "run": "1031-030851_najda_v6_heldout_confirm"}
LEARNING_CURVES = {"najda_v4_nt": "1030-194208_najda_v4_nt", "najda_v4": "1030-194212_najda_v4"}


def recorded(run_id: str, incident_id: str) -> dict[str, Any]:
    for line in (ROOT / "experiments" / "runs" / run_id / "results.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["incident_id"] == incident_id:
            return r
    raise SystemExit(f"{incident_id} not in {run_id}")


def forbid_live_calls() -> None:
    for k in ("ANTHROPIC_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY"):
        os.environ.pop(k, None)


def trajectory(doctor: Any, bundle: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rerun one incident from the cache; returns (resolution dict, truth). Fails if any LLM call was not cached."""
    truth = read_truth(bundle)
    with truth_sealed():
        res, _ = treat_incident(doctor, bundle, truth)
    r = res.to_dict()
    if r.get("error"):
        raise SystemExit(f"{bundle.name}: doctor error (cache miss?): {r['error'][:200]}")
    llm = [s for s in r["steps"] if s["action"] == "llm"]
    missed = [s["i"] for s in llm if not s["result"].get("cached")]
    if missed:
        raise SystemExit(f"{bundle.name}: LLM steps {missed} were not cache hits; refusing to spend")
    return r, truth


def after_fix_chats(truth: dict[str, Any], final_config: dict[str, Any]) -> list[dict[str, Any]]:
    """Transcripts of every chat rerun under the doctor's final config (scripted patient, free)."""
    patient = get_patient(truth.get("patient", DEFAULT_PATIENT))
    snap = {"history": [{"version": 1, "patch": {}, "reason": "final", "actor": "najda", "time": 0.0, "config": final_config}]}
    panel = ControlPanel.from_snapshot(snap, patient.config_cls)
    run = rerun(truth, panel, chats="all")
    return [{"chat_id": c.chat_id, "outcome": c.outcome, "transcript": c.transcript} for c in run.results]


def load_bundle(bundle: Path) -> dict[str, Any]:
    read = lambda name: json.loads((bundle / name).read_text(encoding="utf-8"))  # noqa: E731
    metrics = read("metrics.json")
    return {"chats": read("chats.json"), "config": read("config.json"), "invariants": read("invariants.json"),
            "metrics": {k: v for k, v in metrics.items() if k != "per_chat"}}


def slim(r: dict[str, Any]) -> dict[str, Any]:
    keys = ("doctor", "steps", "report", "root_causes", "actions", "escalated", "final_config", "cost_usd", "llm_calls", "wall_s")
    return {k: r[k] for k in keys}


def export_incident(sel: dict[str, Any]) -> dict[str, Any]:
    bundle = ROOT / "data" / sel["bench"] / sel["id"]
    out: dict[str, Any] = {k: sel[k] for k in ("id", "role", "headline", "headline_ar", "silent")}
    out["bundle"] = load_bundle(bundle)
    out["trajectories"], out["after_fix"] = {}, {}
    for doctor_name, run_id in sel["runs"].items():
        doctor = get_doctor(doctor_name)
        doctor.reset_memory()
        r, truth = trajectory(doctor, bundle)
        rec = recorded(run_id, sel["id"])
        out["patient"], out["family"] = truth.get("patient", DEFAULT_PATIENT), rec["family"]
        t = slim(r)
        t["recorded"] = {"run_id": run_id, "scores": rec["scores"]}
        out["trajectories"][doctor_name] = t
        if any(a["type"] == "patch" for a in r["actions"]) and not r["escalated"]:
            out["after_fix"][doctor_name] = after_fix_chats(truth, r["final_config"])
        print(f"  {sel['id']:22s} {doctor_name:9s} calls={r['llm_calls']} ${r['cost_usd']:.4f} "
              f"{'escalated' if r['escalated'] else 'recovered'} steps={len(r['steps'])}")
    return out


def export_repeat() -> dict[str, Any]:
    """The same doctor meets a fault twice: run 1 learns a playbook, run 2 must hit it with zero LLM calls."""
    doctor = get_doctor(REPEAT["doctor"])
    doctor.reset_memory()
    bench = ROOT / "data" / REPEAT["bench"]
    runs = []
    for inc in (REPEAT["first"], REPEAT["second"]):
        r, truth = trajectory(doctor, bench / inc)
        t = slim(r)
        t["incident_id"], t["family"] = inc, recorded(REPEAT["run"], inc)["family"]
        t["playbook_events"] = [s["result"] for s in r["steps"] if s["action"] == "najda.playbook"]
        t["chats"] = load_bundle(bench / inc)["chats"]
        runs.append(t)
        print(f"  repeat {inc:22s} calls={r['llm_calls']} ${r['cost_usd']:.4f} playbook={[e['event'] for e in t['playbook_events']]}")
    if runs[1]["llm_calls"] != 0:
        raise SystemExit("run 2 of the repeat demo was not a playbook hit; the pack would lie")
    return {"doctor": REPEAT["doctor"], "runs": runs, "playbooks": [p.to_dict() for p in doctor.store().playbooks]}


def md_sections(path: Path) -> list[dict[str, str]]:
    """Split a markdown file into [{heading, body}] on '#'/'##' headings, in order (headings may repeat)."""
    sections: list[dict[str, str]] = []
    cur = {"heading": "", "body": []}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# ") or line.startswith("## "):
            sections.append({"heading": cur["heading"], "body": "\n".join(cur["body"]).strip()})
            cur = {"heading": line.lstrip("# ").strip(), "body": []}
        else:
            cur["body"].append(line)
    sections.append({"heading": cur["heading"], "body": "\n".join(cur["body"]).strip()})
    return [s for s in sections if s["heading"] or s["body"]]


def export_results() -> None:
    res = OUT / "results"
    res.mkdir(parents=True, exist_ok=True)
    docs = {name: md_sections(ROOT / "docs" / name) for name in ("RESULTS.md", "PREREGISTRATION.md")}
    (res / "sections.json").write_text(json.dumps(docs, indent=1, ensure_ascii=False), encoding="utf-8")
    for f in (ROOT / "experiments" / "figures").glob("*.csv"):
        shutil.copy(f, res / f.name)
    rows: list[dict[str, str]] = []
    for doctor, run in LEARNING_CURVES.items():
        for row in csv.DictReader((ROOT / "experiments" / "learning_curve" / run / "curve.csv").open(encoding="utf-8")):
            rows.append({"doctor": doctor, **row})
    with (res / "learning_curve_streams.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    shutil.copy(ROOT / "experiments" / "confirm_report.md", res / "confirm_report.md")


def main() -> None:
    forbid_live_calls()
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "incidents").mkdir(parents=True)
    print("Regenerating trajectories from the LLM cache (no key, $0):")
    manifest: dict[str, Any] = {"generated": datetime.now().astimezone().isoformat(timespec="seconds"),
                                "commit": subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                                                         text=True).stdout.strip(),
                                "incidents": []}
    for sel in SELECTION:
        inc = export_incident(sel)
        (OUT / "incidents" / f"{sel['id']}.json").write_text(json.dumps(inc, indent=1, ensure_ascii=False), encoding="utf-8")
        manifest["incidents"].append({k: inc[k] for k in ("id", "role", "family", "patient", "headline", "headline_ar")}
                                     | {"doctors": list(inc["trajectories"])})
    rep = export_repeat()
    (OUT / "repeat.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    manifest["repeat"] = {"doctor": rep["doctor"], "incidents": [r["incident_id"] for r in rep["runs"]]}
    export_results()
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    size = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print(f"Wrote {OUT.relative_to(ROOT)}/ ({size / 1e6:.1f} MB, commit {manifest['commit']})")


if __name__ == "__main__":
    main()
