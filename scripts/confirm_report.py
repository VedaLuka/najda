"""Step 7 confirmation-run report: arm tables with bootstrap CIs, per-family counts, hypothesis checks.

  python scripts/confirm_report.py            # markdown to stdout (paste into docs/PREREGISTRATION.md)

Reads the step-7 runs from experiments/log.jsonl (note contains 'step 7 pre-registered confirmation run') and their
results.jsonl. No scoring here: the scorer already ran; this only tabulates.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from report import bootstrap_ci, load_results  # noqa: E402

TAG = "step 7 pre-registered confirmation run"
LABELS = {"C-1": "single_llm", "C-2": "najda_v5 COLD", "C-3": "najda_v6 COLD", "C-4": "najda_v6 COLD, Haiku big",
          "C-5": "najda_v5 COLD", "C-6": "najda_v6 COLD"}


def step7_runs() -> dict[str, dict]:
    runs = {}
    for line in (ROOT / "experiments" / "log.jsonl").read_text().splitlines():
        d = json.loads(line)
        if TAG in d.get("note", ""):
            arm = d["note"].rsplit(": ", 1)[-1].split()[0]  # 'C-3'
            runs[arm] = d
    return runs


def arm_table(runs: dict[str, dict], arms: list[str]) -> list[str]:
    out = ["| Arm | n | Outcome [95% CI] | Recovered | RC@1 | Esc. correct | Dangerous | Cost $ | $/incident | LLM calls | Run |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for arm in arms:
        if arm not in runs:
            out.append(f"| {LABELS[arm]} | not run | | | | | | | | | |")
            continue
        d, m = runs[arm], runs[arm]["metrics"]
        vals = [bool(r["scores"]["outcome_correct"]) for r in load_results(d["run_id"])]
        lo, hi = bootstrap_ci(vals)
        out.append(f"| {LABELS[arm]} | {m['n']} | **{m['outcome_correct']:.3f} [{lo:.3f}, {hi:.3f}]** | {m['recovered']:.3f} | "
                   f"{m['root_cause_top1']:.3f} | {m['escalation_correct']:.3f} | {int(m['dangerous_actions'])} | "
                   f"{m['cost_usd']:.4f} | {m['cost_usd'] / m['n']:.4f} | {m['llm_calls']} | {d['run_id']} |")
    return out


def family_table(runs: dict[str, dict], arms: list[str]) -> list[str]:
    per: dict[str, dict[str, int]] = defaultdict(dict)
    n_by_family: dict[str, int] = {}
    present = [a for a in arms if a in runs]
    for arm in present:
        for r in load_results(runs[arm]["run_id"]):
            fam = r["family"]
            n_by_family[fam] = n_by_family.get(fam, 0) + (1 if arm == present[0] else 0)
            per[fam][arm] = per[fam].get(arm, 0) + int(bool(r["scores"]["outcome_correct"]))
    out = ["| family | n | " + " | ".join(LABELS[a] for a in present) + " |", "|---|---|" + "---|" * len(present)]
    for fam in sorted(per):
        out.append(f"| {fam} | {n_by_family[fam]} | " + " | ".join(str(per[fam].get(a, 0)) for a in present) + " |")
    return out


def count(runs: dict[str, dict], arm: str) -> int | None:
    if arm not in runs:
        return None
    return sum(int(bool(r["scores"]["outcome_correct"])) for r in load_results(runs[arm]["run_id"]))


def changed(runs: dict[str, dict], a: str, b: str) -> tuple[list[str], list[str]]:
    """Incidents b got right and a did not (fixed), and the reverse (broken)."""
    if a not in runs or b not in runs:
        return [], []
    ra = {r["incident_id"]: bool(r["scores"]["outcome_correct"]) for r in load_results(runs[a]["run_id"])}
    rb = {r["incident_id"]: bool(r["scores"]["outcome_correct"]) for r in load_results(runs[b]["run_id"])}
    fixed = sorted(i for i in ra if rb.get(i) and not ra[i])
    broken = sorted(i for i in ra if ra[i] and not rb.get(i))
    return fixed, broken


def verdict(ok: bool | None) -> str:
    return "not run" if ok is None else ("supported" if ok else "NOT supported")


def main() -> None:
    runs = step7_runs()
    print("## heldout-confirm (order bot, 25 incidents, held-out families, new seeds)\n")
    print("\n".join(arm_table(runs, ["C-1", "C-2", "C-3", "C-4"])))
    print("\nOutcome by family (correct / n):\n")
    print("\n".join(family_table(runs, ["C-1", "C-2", "C-3", "C-4"])))
    f, b = changed(runs, "C-2", "C-3")
    print(f"\nv6 vs v5 on heldout-confirm: fixed {len(f)} {f}, broken {len(b)} {b}")
    print("\n## transfer-confirm (Hajz, 15 incidents, transfer families, new seeds)\n")
    print("\n".join(arm_table(runs, ["C-5", "C-6"])))
    print("\nOutcome by family (correct / n):\n")
    print("\n".join(family_table(runs, ["C-5", "C-6"])))
    f, b = changed(runs, "C-5", "C-6")
    print(f"\nv6 vs v5 on transfer-confirm: fixed {len(f)} {f}, broken {len(b)} {b}")
    c1, c2, c3, c4, c5, c6 = (count(runs, a) for a in ["C-1", "C-2", "C-3", "C-4", "C-5", "C-6"])
    dang = [int(runs[a]["metrics"]["dangerous_actions"]) for a in ["C-3", "C-4", "C-6"] if a in runs]
    print("\n## Hypotheses\n")
    print("| | Pre-registered | Result | Verdict |\n|---|---|---|---|")
    print(f"| C1 | v6 >= v5 on heldout-confirm | {c3} vs {c2} of 25 | {verdict(None if None in (c2, c3) else c3 >= c2)} |")
    print(f"| C2 | v6 > single_llm on heldout-confirm | {c3} vs {c1} of 25 | {verdict(None if None in (c1, c3) else c3 > c1)} |")
    print(f"| C3 | zero dangerous actions for v6 on both sets | {dang} (C-3, C-4, C-6) | {verdict(None if len(dang) < 3 else sum(dang) == 0)} |")
    print(f"| C4 | v6 >= v5 on transfer-confirm | {c6} vs {c5} of 15 | {verdict(None if None in (c5, c6) else c6 >= c5)} |")


if __name__ == "__main__":
    main()
