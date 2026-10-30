"""Turn experiments/log.jsonl bench runs into markdown tables for the README and slides.

  python scripts/report.py            # print tables
  python scripts/report.py --write    # also write docs/RESULTS.md
The oracle reads ground truth: it appears only as a bench sanity line, never as a system.
"""
from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SANITY_ONLY = {"oracle"}
VERSION_FILE = ROOT / "data" / "incidents" / "BENCH_VERSION"
BENCH_VERSION = VERSION_FILE.read_text().strip() if VERSION_FILE.exists() else "1.0"


def latest_by_doctor(rows: list[dict], split: str) -> dict[str, dict]:
    """Latest full-split run per doctor on the current bench version (limit runs are probes). Memory-on
    streams are listed apart as `<doctor>+memory` (the latest seed; see experiments/learning_curve/ for all)."""
    out: dict[str, dict] = {}
    for r in rows:
        if (r["split"] == split and not r.get("limit") and r.get("bench", "incidents") == "incidents"
                and r.get("bench_version", "1.0") == BENCH_VERSION and r.get("replay_brain", "scripted") == "scripted"):
            out[r["doctor"] + ("+memory" if r.get("memory") == "on" else "")] = r
    return out


def pct(x: float | None) -> str:
    return "-" if x is None else f"{x:.3f}"


CI_METRICS = ("outcome_correct", "recovered", "escalation_correct", "root_cause_top1", "dangerous")


def load_results(run_id: str) -> list[dict]:
    path = ROOT / "experiments" / "runs" / run_id / "results.jsonl"
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []


def bootstrap_ci(values: list[bool], n_boot: int = 2000, seed: int = 0) -> tuple[float, float]:
    """95% percentile bootstrap CI of a rate over incidents (resampled with replacement)."""
    rng = random.Random(seed)
    n = len(values)
    if n == 0:
        return 0.0, 0.0
    means = sorted(sum(rng.choice(values) for _ in range(n)) / n for _ in range(n_boot))
    return means[int(0.025 * n_boot)], means[int(0.975 * n_boot) - 1]


def confidence_intervals(latest: dict[str, dict], split: str) -> list[str]:
    out = ["", f"## 95% bootstrap confidence intervals ({split}, 2000 resamples over incidents)", "",
           "| Doctor | n | " + " | ".join(CI_METRICS) + " |", "|---|---|" + "---|" * len(CI_METRICS)]
    for name, r in latest.items():
        if name in SANITY_ONLY:
            continue
        rows = load_results(r["run_id"])
        if not rows:
            continue
        cells = []
        for m in CI_METRICS:
            vals = [bool(x["scores"][m]) for x in rows]
            lo, hi = bootstrap_ci(vals)
            cells.append(f"{sum(vals) / len(vals):.3f} [{lo:.3f}, {hi:.3f}]")
        out.append(f"| `{name}` | {len(rows)} | " + " | ".join(cells) + " |")
    return out


def calibration(latest: dict[str, dict], doctor: str, split: str) -> list[str]:
    """Top hypothesis confidence (as logged by the doctor) vs whether the incident outcome was correct."""
    if doctor not in latest:
        return []
    buckets: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    for row in load_results(latest[doctor]["run_id"]):
        causes = row["resolution"]["root_causes"]
        if not causes:
            continue
        c = float(causes[0]["confidence"])
        b = "<0.5" if c < 0.5 else "0.5-0.7" if c < 0.7 else "0.7-0.9" if c < 0.9 else ">=0.9"
        buckets[b].append((c, bool(row["scores"]["outcome_correct"])))
    if not buckets:
        return []
    out = ["", f"## Calibration of `{doctor}` ({split}): top-hypothesis confidence vs outcome_correct", "",
           "| Confidence bucket | n | outcome_correct | mean confidence |", "|---|---|---|---|"]
    for b in ("<0.5", "0.5-0.7", "0.7-0.9", ">=0.9"):
        if b in buckets:
            xs = buckets[b]
            out.append(f"| {b} | {len(xs)} | {sum(ok for _, ok in xs) / len(xs):.3f} | "
                       f"{sum(c for c, _ in xs) / len(xs):.3f} |")
    return out


def progression(latest: dict[str, dict], split: str) -> list[str]:
    out = [f"## Progression ({split}, IncidentBench v{BENCH_VERSION}, primary = outcome_correct)", "",
           "| # | Doctor | n | Outcome | Recovered | RC@1 | RC@3 | Esc. correct | Dangerous | Cost $ | $/correct | Steps | LLM calls | Commit | Note |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, (name, r) in enumerate(((n, r) for n, r in latest.items() if n not in SANITY_ONLY), 1):
        m = r["metrics"]
        cpc = "-" if m["cost_per_correct_usd"] is None else f"{m['cost_per_correct_usd']:.4f}"
        out.append(f"| {k} | `{name}` | {m['n']} | **{pct(m['outcome_correct'])}** | {pct(m['recovered'])} | "
                   f"{pct(m['root_cause_top1'])} | {pct(m['root_cause_top3'])} | {pct(m['escalation_correct'])} | "
                   f"{pct(m['dangerous'])} | {m['cost_usd']:.4f} | {cpc} | {m['mean_steps']} | {m['llm_calls']} | "
                   f"{r['git']['commit'] or '-'}{'*' if r['git'].get('dirty') else ''} | {r['note']} |")
    return out


def per_family(latest: dict[str, dict], split: str) -> list[str]:
    doctors = [d for d in latest if d not in SANITY_ONLY]
    families = sorted({f for d in doctors for f in latest[d]["metrics"]["per_family"]})
    out = ["", f"## Outcome by fault family ({split})", "",
           "| Family | n | " + " | ".join(f"`{d}`" for d in doctors) + " |",
           "|---|---|" + "---|" * len(doctors)]
    for fam in families:
        n = next(latest[d]["metrics"]["per_family"][fam]["n"] for d in doctors if fam in latest[d]["metrics"]["per_family"])
        cells = [pct(latest[d]["metrics"]["per_family"].get(fam, {}).get("outcome_correct")) for d in doctors]
        out.append(f"| {fam} | {n} | " + " | ".join(cells) + " |")
    return out


def dev_vs_heldout(dev: dict[str, dict], held: dict[str, dict]) -> list[str]:
    doctors = [d for d in dev if d in held and d not in SANITY_ONLY]
    if not doctors:
        return []
    out = ["", "## Dev vs heldout (outcome_correct) — heldout runs are milestones only", "",
           "| Doctor | Dev | Heldout | Drop |", "|---|---|---|---|"]
    for d in doctors:
        a, b = dev[d]["primary"], held[d]["primary"]
        out.append(f"| `{d}` | {a:.3f} | {b:.3f} | {b - a:+.3f} |")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--calibrate", default="najda_v2", help="doctor whose logged confidences get a calibration table")
    a = ap.parse_args()
    log = ROOT / "experiments" / "log.jsonl"
    rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()] if log.exists() else []
    rows = [r for r in rows if r.get("kind") == "bench"]
    if not rows:
        print("No bench runs logged yet.")
        return
    dev, held = latest_by_doctor(rows, "dev"), latest_by_doctor(rows, "heldout")
    out: list[str] = []
    if dev:
        out += progression(dev, "dev") + per_family(dev, "dev") + confidence_intervals(dev, "dev")
        out += calibration(dev, a.calibrate, "dev")
    if held:
        out += ["", "> !! Heldout results below: milestones only, never tune on them."]
        out += progression(held, "heldout")
    out += dev_vs_heldout(dev, held)
    sanity = [f"`{d}` {s}={r['primary']:.3f}" for s, runs in (("dev", dev), ("heldout", held))
              for d, r in runs.items() if d in SANITY_ONLY]
    if sanity:
        out += ["", "Bench sanity (oracle reads ground truth, must be 1.000): " + ", ".join(sanity)]
    out += ["", "`*` = run made from a dirty working tree."]
    text = "\n".join(out)
    print(text)
    if a.write:
        (ROOT / "docs" / "RESULTS.md").write_text("# Results (auto-generated by scripts/report.py)\n\n" + text + "\n")
        print("\nWrote docs/RESULTS.md")


if __name__ == "__main__":
    main()
