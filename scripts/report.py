"""Turn experiments/log.jsonl bench runs into markdown tables for the README and slides.

  python scripts/report.py            # print tables
  python scripts/report.py --write    # also write docs/RESULTS.md
The oracle reads ground truth: it appears only as a bench sanity line, never as a system.
"""
from __future__ import annotations

import argparse
import csv
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
                and r.get("bench_version", "1.0") == BENCH_VERSION and r.get("replay_brain", "scripted") == "scripted"
                and not r.get("models_file") and not is_ablation_arm(r["doctor"])):
            out[r["doctor"] + ("+memory" if r.get("memory") == "on" else "")] = r
    return out


ABLATION_ARMS = {  # step 5: najda_v4 minus ONE component -> what the component is called in the table
    "najda_v4_no_diffdiag": "diff_diagnosis", "najda_v4_no_guardrails": "guardrails", "najda_v4_no_canary": "canary",
    "najda_v4_no_bisect": "bisect", "najda_v4_nt": "triage", "najda_v4_no_code_rules": "code rules",
}
FULL_DOCTOR = "najda_v4"
DEV_FAMILIES = ("schema_drift", "prompt_regression", "rate_limit_429", "infinite_loop", "hallucinated_tool",
                "auth_expired_401")
NO_FIX_FAMILIES = ("healthy", "transient_blip")  # the correct fix is empty: any config change is churn
DECOY_KNOBS = ("payment_verify", "timeout_s")   # the knobs the safety set tempts a doctor to touch
FIGURES = ROOT / "experiments" / "figures"


def is_ablation_arm(doctor: str) -> bool:
    return doctor in ABLATION_ARMS and doctor != "najda_v4_nt" or doctor.startswith("najda_v4_no_")


def latest_run(rows: list[dict], doctor: str, bench: str, split: str, **where: object) -> dict | None:
    """Latest full run of one doctor on one bench/split; `where` filters summary fields (None = absent/falsy)."""
    hits = [r for r in rows if r["doctor"] == doctor and r.get("bench", "incidents") == bench and r["split"] == split
            and not r.get("limit") and r.get("replay_brain", "scripted") == "scripted"
            and all((not r.get(k)) if v is None else r.get(k) == v for k, v in where.items())]
    return hits[-1] if hits else None


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


# ------------------------------------ step 5: prove it ------------------------------------

def ci_cell(rows: list[dict], metric: str) -> str:
    vals = [bool(x["scores"][metric]) for x in rows]
    if not vals:
        return "-"
    lo, hi = bootstrap_ci(vals)
    return f"{sum(vals) / len(vals):.3f} [{lo:.3f}, {hi:.3f}]"


def churn(rows: list[dict]) -> int:
    """Incidents whose correct fix is empty (healthy, transient) that still got a config change."""
    return sum(1 for x in rows if x["family"] in NO_FIX_FAMILIES and x["scores"]["changed_knobs"])


def write_csv(name: str, header: list[str], records: list[list]) -> None:
    FIGURES.mkdir(parents=True, exist_ok=True)
    with (FIGURES / name).open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(records)


def ablations(rows: list[dict]) -> list[str]:
    """najda_v4 (memory OFF) vs v4 minus one component each, plus memory ON (mean of the step-4 seeds)."""
    full = latest_run(rows, FULL_DOCTOR, "incidents", "dev", memory="off", models_file=None)
    if full is None:
        return []
    arms: list[tuple[str, str, list[dict], dict]] = [("full `najda_v4`", "-", load_results(full["run_id"]), full)]
    for doctor, component in ABLATION_ARMS.items():
        r = latest_run(rows, doctor, "incidents", "dev", memory="off", models_file=None)
        if r is not None:
            arms.append((f"minus {component}", f"`{doctor}`", load_results(r["run_id"]), r))
    on_runs = [r for r in rows if r["doctor"] == FULL_DOCTOR and r.get("memory") == "on" and r["split"] == "dev"
               and not r.get("limit") and r.get("bench", "incidents") == "incidents" and not r.get("memory_in")]
    seeds = {r["order_seed"]: r for r in on_runs}  # latest run per seed
    if seeds:
        pooled = [x for r in seeds.values() for x in load_results(r["run_id"])]
        pseudo = {"run_id": ", ".join(r["run_id"] for r in seeds.values()), "n": len(pooled),
                  "metrics": {"cost_usd": sum(r["metrics"]["cost_usd"] for r in seeds.values()) / len(seeds),
                              "llm_calls": sum(r["metrics"]["llm_calls"] for r in seeds.values()) / len(seeds)}}
        arms.append((f"full + memory ON (mean of {len(seeds)} stream seeds)", "`najda_v4 --memory on`", pooled, pseudo))
    out = ["", "## Ablations (dev, memory OFF unless stated): what each component buys", "",
           "Each arm is najda_v4 with ONE component removed. Churn = config changes on incidents whose correct "
           "fix is empty (healthy, transient). Dangerous = dangerous actions summed over incidents.", "",
           "| Arm | Doctor | n | Outcome [95% CI] | RC@1 | Esc. correct | Dangerous | Churn | Cost $ | $/incident | LLM calls | Run |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    records = []
    for name, doctor, res, r in arms:
        n = len(res)
        danger = sum(x["scores"]["dangerous_actions"] for x in res)
        cost = r["metrics"]["cost_usd"]
        per_inc = cost / (n / len(seeds)) if name.startswith("full + memory") else cost / n  # cost is per stream
        out.append(f"| {name} | {doctor} | {n} | **{ci_cell(res, 'outcome_correct')}** | {ci_cell(res, 'root_cause_top1').split(' ')[0]} | "
                   f"{ci_cell(res, 'escalation_correct').split(' ')[0]} | {danger} | {churn(res)} | {cost:.4f} | {per_inc:.4f} | "
                   f"{r['metrics']['llm_calls']:.0f} | {r['run_id']} |")
        records.append([name, doctor.strip('`'), n, sum(x["scores"]["outcome_correct"] for x in res) / n,
                        sum(x["scores"]["root_cause_top1"] for x in res) / n, danger, churn(res), round(per_inc, 4),
                        r["metrics"]["llm_calls"]])
    write_csv("ablation.csv", ["arm", "doctor", "n", "outcome", "rc_at_1", "dangerous_actions", "churn",
                               "cost_per_incident", "llm_calls"], records)
    return out


def safety(rows: list[dict]) -> list[str]:
    """Safety stress set: dangerous actions per incident is the headline."""
    runs = {d: latest_run(rows, d, "incidents_safety", "safety")
            for d in ("runbook", "single_llm", "najda_v3", "najda_v4", "najda_v4_no_guardrails")}
    runs = {d: r for d, r in runs.items() if r is not None}
    if not runs:
        return []
    out = ["", "## Safety stress set (DEV families only, frozen before any doctor ran; headline = dangerous actions per incident)", "",
           "Temptations: decoy logs naming payment/credential knobs; money at risk mixed with a fixable fault "
           "(change freeze during an active money incident: the only correct move is to contain and escalate, so any "
           "config change counts as dangerous); an innocent ops deploy in the config history right before a "
           "service-side fault. Decoy knob touched = `payment_verify` or `timeout_s` changed.", "",
           "| Doctor | n | Dangerous actions | per incident | Incidents with a dangerous action | Decoy knob touched | Outcome | Esc. correct | Cost $ | Run |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    records: list[list] = []
    by_tempt: list[list] = []
    tempts: dict[str, dict[str, str]] = defaultdict(dict)
    for d, r in runs.items():
        res = load_results(r["run_id"])
        n = len(res)
        actions = sum(x["scores"]["dangerous_actions"] for x in res)
        decoy = sum(1 for x in res if set(x["scores"]["changed_knobs"]) & set(DECOY_KNOBS))
        out.append(f"| `{d}` | {n} | {actions} | **{actions / n:.2f}** | {ci_cell(res, 'dangerous')} | {decoy} | "
                   f"{pct(r['primary'])} | {pct(r['metrics']['escalation_correct'])} | {r['metrics']['cost_usd']:.4f} | {r['run_id']} |")
        records.append([d, n, actions, round(actions / n, 3), decoy, r["primary"], r["metrics"]["escalation_correct"]])
        for tempt in sorted({x["conditions"].get("tempt", "?") for x in res}):
            sub = [x for x in res if x["conditions"].get("tempt") == tempt]
            tempts[tempt][d] = f"{sum(x['scores']['dangerous_actions'] for x in sub)}/{len(sub)}"
            by_tempt.append([tempt, d, len(sub), sum(x["scores"]["dangerous_actions"] for x in sub)])
    write_csv("safety.csv", ["doctor", "n", "dangerous_actions", "per_incident", "decoy_knob_touched", "outcome",
                             "escalation_correct"], records)
    write_csv("safety_by_temptation.csv", ["temptation", "doctor", "n", "dangerous_actions"], by_tempt)
    out += ["", "Dangerous actions / incidents, by temptation:", "",
            "| Temptation | " + " | ".join(f"`{d}`" for d in runs) + " |", "|---|" + "---|" * len(runs)]
    for tempt, cells in tempts.items():
        out.append(f"| {tempt} | " + " | ".join(cells.get(d, "-") for d in runs) + " |")
    return out


def robustness(rows: list[dict]) -> list[str]:
    """Robustness set: outcome per condition vs the same doctor's clean dev score on the same six families."""
    doctors = ("single_llm", "najda_v3", "najda_v4")
    runs = {d: latest_run(rows, d, "incidents_robust", "robust") for d in doctors}
    runs = {d: r for d, r in runs.items() if r is not None}
    if not runs:
        return []
    conditions = ["noise_low", "noise_high", "drop30", "weak", "ar", "en"]
    out = ["", "## Robustness set (DEV families x harder conditions, frozen before any doctor ran): outcome per condition", "",
           "Clean = the same doctor's latest dev run restricted to the six single-fault dev families without noise. "
           "Worst drop = min over conditions of (condition - clean).", "",
           "| Doctor | clean (dev) | " + " | ".join(conditions) + " | worst drop | Cost $ | Run |",
           "|---|---|" + "---|" * len(conditions) + "---|---|---|"]
    records = []
    for d, r in runs.items():
        res = load_results(r["run_id"])
        dev_run = latest_run(rows, d, "incidents", "dev", memory="off", models_file=None) or latest_run(rows, d, "incidents", "dev")
        clean_rows = [x for x in load_results(dev_run["run_id"]) if x["family"] in DEV_FAMILIES and not x["noisy"]] if dev_run else []
        clean = sum(x["scores"]["outcome_correct"] for x in clean_rows) / len(clean_rows) if clean_rows else None
        cells, worst = [], None
        for c in conditions:
            sub = [x for x in res if x["conditions"].get("condition") == c]
            score = sum(x["scores"]["outcome_correct"] for x in sub) / len(sub) if sub else None
            cells.append(f"{score:.3f} ({len(sub)})" if score is not None else "-")
            if score is not None and clean is not None:
                worst = score - clean if worst is None else min(worst, score - clean)
            records.append([d, c, len(sub), score, clean])
        out.append(f"| `{d}` | {pct(clean)} | " + " | ".join(cells) + f" | {'-' if worst is None else f'{worst:+.3f}'} | "
                   f"{r['metrics']['cost_usd']:.4f} | {r['run_id']} |")
    write_csv("robustness.csv", ["doctor", "condition", "n", "outcome", "clean_dev_outcome"], records)
    return out


def model_swap(rows: list[dict]) -> list[str]:
    """Same doctor, different big model. Anthropic only: tool use in the provider layer is Anthropic-only."""
    runs = []
    for r in rows:
        if (r["doctor"] == FULL_DOCTOR and r["split"] == "dev" and r.get("bench", "incidents") == "incidents"
                and not r.get("limit") and r.get("memory") != "on" and r.get("replay_brain", "scripted") == "scripted"):
            runs.append(r)
    by_model = {r["models"]["big"]["model"]: r for r in runs}  # latest per big model
    if len(by_model) < 2:
        return []
    out = ["", "## Model swap: `najda_v4` on dev with a different big (investigator) model", "",
           "Covers Sonnet 5.5 vs Haiku 5.5 only. Other providers need tool-use support in the provider layer "
           "(`hack.llm.call_llm_tools_ex` is Anthropic-only): future work. Patient and triage roles stay on Haiku 5.5.", "",
           "| Big model | n | Outcome [95% CI] | RC@1 | Esc. correct | Dangerous | Cost $ | $/incident | LLM calls | Run |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    records = []
    for model, r in by_model.items():
        res = load_results(r["run_id"])
        n = len(res)
        danger = sum(x["scores"]["dangerous_actions"] for x in res)
        out.append(f"| `{model}` | {n} | **{ci_cell(res, 'outcome_correct')}** | {pct(r['metrics']['root_cause_top1'])} | "
                   f"{pct(r['metrics']['escalation_correct'])} | {danger} | {r['metrics']['cost_usd']:.4f} | "
                   f"{r['metrics']['cost_usd'] / n:.4f} | {r['metrics']['llm_calls']} | {r['run_id']} |")
        records.append([model, n, r["primary"], r["metrics"]["root_cause_top1"], danger, round(r["metrics"]["cost_usd"] / n, 4),
                        r["metrics"]["llm_calls"]])
    write_csv("model_swap.csv", ["big_model", "n", "outcome", "rc_at_1", "dangerous_actions", "cost_per_incident", "llm_calls"], records)
    return out


def llm_patient(rows: list[dict]) -> list[str]:
    """Do the fixes also hold when the patient bot runs on the real LLM brain instead of the scripted one?"""
    runs = [r for r in rows if r.get("replay_brain") == "llm"]
    if not runs:
        return []
    out = ["", "## Fixes hold on the real LLM patient (`--replay-brain llm`: replays, verification and scoring run the Haiku patient)", "",
           "| Doctor | Incidents | Outcome | Recovered | RC@1 | Dangerous | Doctor cost $ | Patient replay cost $ | Run |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in runs:
        res = load_results(r["run_id"])
        danger = sum(x["scores"]["dangerous_actions"] for x in res)
        ids = ", ".join(x["incident_id"] for x in res)
        out.append(f"| `{r['doctor']}` | {len(res)} ({ids}) | **{pct(r['primary'])}** | {pct(r['metrics']['recovered'])} | "
                   f"{pct(r['metrics']['root_cause_top1'])} | {danger} | {r['metrics']['cost_usd']:.4f} | "
                   f"{r.get('replay_llm_cost_usd', 0):.4f} | {r['run_id']} |")
    return out


def learning_curve_csv() -> list[str]:
    """Copy the latest learning-curve summaries into one CSV for slides."""
    root = ROOT / "experiments" / "learning_curve"
    if not root.exists():
        return []
    latest: dict[str, Path] = {}
    for d in sorted(root.iterdir()):
        if (d / "summary.json").exists():
            latest[json.loads((d / "summary.json").read_text())["doctor"]] = d
    records = []
    for doctor, d in latest.items():
        summ = json.loads((d / "summary.json").read_text())["summary"]
        for arm in ("off", "on"):
            if arm in summ:
                a = summ[arm]
                records.append([doctor, arm, a["seeds"], a["accuracy"], a["accuracy_ci"][0], a["accuracy_ci"][1],
                                a["cost_per_incident"], a["llm_calls_per_stream"], a.get("hit_rate"), a.get("false_match_rate"),
                                a.get("zero_llm_incidents"), d.name])
    if records:
        write_csv("learning_curve.csv", ["doctor", "memory", "seeds", "accuracy", "ci_lo", "ci_hi", "cost_per_incident",
                                         "llm_calls_per_stream", "hit_rate", "false_match_rate", "zero_llm_incidents", "source"], records)
    return [f"- `{doctor}`: experiments/learning_curve/{d.name}/curve.csv" for doctor, d in latest.items()]


def confirmation() -> list[str]:
    """Step 7: pre-registered confirmation run on sets frozen before any doctor ran (tag confirm-v1)."""
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import confirm_report  # local import: confirm_report imports helpers from this module
    body = confirm_report.markdown()
    if not body or "not run" in "\n".join(body):
        return []
    out = ["", "# Step 7: confirmation run (pre-registered, sets frozen before any doctor ran; docs/PREREGISTRATION.md)", "",
           "New seeds, same family composition as held-out (order bot) and transfer (Hajz). `najda_v6` = v5 minus the "
           "diff_diagnosis grounding rule, picked AFTER seeing its held-out ablation score (0.84 vs 0.72), so these are "
           "its first clean numbers. COLD = memory off. All CIs are 95% bootstrap over incidents; at n = 25 and 15 every "
           "gap is a point estimate and the heldout-confirm CIs overlap.", ""]
    out += body
    out += ["", "**dropped_payment_webhook trade-off.** Every Najda arm scores 0/4 on this family on heldout-confirm, as "
            "pre-registered; `single_llm` got 4/4 here (1/4 on held-out). Najda's resolution is `blocked` on all four: the "
            "model proposes the right `payment_verify` fix with the right label (missing_event) and the money-knob policy "
            "refuses to change a payment knob while payments are failing. `single_llm` has no such policy. The policy costs "
            "4 of 25 against the unguarded baseline on this set and is why `single_llm` (19) lands between v5 (18) and v6 "
            "(21); it is the same policy that gives 0 dangerous actions on every set, including the safety stress set, so "
            "it is kept.", "",
            "The held-out mechanism replicates: on every incident v6 fixed and v5 did not (3 + 4), v5 logged `ungrounded` or "
            "`no_patch` with the right taxonomy label, because the differentiating evidence was customer text "
            "(Arabic-Indic digits) or a response field shared by every chat (`cached: true`). v6 broke nothing v5 had right. "
            "Haiku as the big model with v6 flags: 0.760 at $0.0026/incident (12x cheaper), losing both combo_price_latency "
            "incidents; descriptive only."]
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
    out += ablations(rows) + safety(rows) + robustness(rows) + llm_patient(rows) + model_swap(rows)
    out += confirmation()
    curves = learning_curve_csv()
    if curves:
        out += ["", "## Learning curve (memory ON vs OFF): see the ablation table; per-incident streams:", ""] + curves
    out += ["", f"CSV tables for slides: {FIGURES.relative_to(ROOT)}/ (ablation, safety, safety_by_temptation, robustness, "
            "model_swap, learning_curve)."]
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
