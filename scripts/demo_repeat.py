"""Demo: the same doctor meets a fault twice. Run 1 investigates with the big model and learns a playbook;
run 2 should be a playbook hit: no LLM call, same guardrails and verification.

  python scripts/demo_repeat.py --incident dev-001 --second dev-002   # a sibling incident: generalisation
  python scripts/demo_repeat.py --incident dev-009                     # the very same incident twice

Prints a side-by-side and saves both trajectories under experiments/demo/<ts>/.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hack.bench.harness import treat_incident  # noqa: E402
from hack.bench.score import score_incident  # noqa: E402
from hack.bench.seal import truth_sealed  # noqa: E402
from hack.bench.truth import read_truth  # noqa: E402
from hack.doctors import get_doctor  # noqa: E402

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass


def run_one(doctor, bundle: Path) -> dict:
    truth = read_truth(bundle)
    with truth_sealed():
        res, initial = treat_incident(doctor, bundle, truth)
    r = res.to_dict()
    playbook = [s["result"] for s in r["steps"] if s["action"] == "najda.playbook"]
    actions = [s["action"] for s in r["steps"] if not s["action"].startswith("najda.")]
    return {"incident": bundle.name, "family": truth["family"], "scores": score_incident(truth, r, initial),
            "cost_usd": r["cost_usd"], "llm_calls": r["llm_calls"], "steps": len(r["steps"]), "actions": actions,
            "escalated": r["escalated"], "patches": [a["patch"] for a in r["actions"] if a["type"] == "patch"],
            "playbook_events": playbook, "root_cause": r["root_causes"][0]["label"] if r["root_causes"] else None,
            "trajectory": r["steps"], "report": r["report"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--doctor", default="najda_v4_nt")
    ap.add_argument("--incident", default="dev-001")
    ap.add_argument("--second", help="incident for run 2 (default: the same one)")
    ap.add_argument("--split", default="dev")
    a = ap.parse_args()
    bench = ROOT / "data" / "incidents" / a.split
    doctor = get_doctor(a.doctor)
    runs = [run_one(doctor, bench / a.incident), run_one(doctor, bench / (a.second or a.incident))]
    out = ROOT / "experiments" / "demo" / f"{datetime.now().strftime('%m%d-%H%M%S')}_{a.incident}_{a.second or a.incident}"
    out.mkdir(parents=True)
    for i, r in enumerate(runs, 1):
        (out / f"run{i}.json").write_text(json.dumps(r, indent=1, ensure_ascii=False, default=str))
    doctor.save_memory(out / "playbooks.json")

    def col(r: dict) -> list[str]:
        ev = [e["event"] for e in r["playbook_events"]]
        return [r["incident"], r["family"], f"${r['cost_usd']:.4f}", str(r["llm_calls"]), str(r["steps"]),
                str(r["root_cause"]), json.dumps(r["patches"]), "escalated" if r["escalated"] else "recovered",
                "yes" if r["scores"]["outcome_correct"] else "no", ",".join(ev) or "-"]

    labels = ["incident", "family", "cost", "LLM calls", "steps", "root cause", "patches", "status", "outcome correct", "playbook"]
    c1, c2 = col(runs[0]), col(runs[1])
    w = max(len(x) for x in labels)
    w1 = max(len(x) for x in c1)
    print(f"{'':{w}}  {'run 1 (cold)':{w1}}  run 2 (with memory)")
    for lab, x, y in zip(labels, c1, c2):
        print(f"{lab:{w}}  {x:{w1}}  {y}")
    saved = runs[0]["cost_usd"] - runs[1]["cost_usd"]
    print(f"\nsaved ${saved:.4f} ({saved / runs[0]['cost_usd']:.0%}) and {runs[0]['llm_calls'] - runs[1]['llm_calls']} LLM calls"
          if runs[0]["cost_usd"] else "")
    print(f"trajectories -> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
