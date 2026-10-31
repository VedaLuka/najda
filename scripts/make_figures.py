"""Charts for the README and slides, drawn from recorded runs only (no API calls).

Every number comes from experiments/runs/<run_id>/results.jsonl or experiments/learning_curve/*/curve.csv, so the
figures regenerate from the same evidence the tables use. Output: docs/figures/<name>.png (1920x1080) + .svg.

    python scripts/make_figures.py
"""
from __future__ import annotations

import csv
import sys
import textwrap
from collections import defaultdict
from pathlib import Path

import matplotlib
import matplotlib.ticker

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from report import bootstrap_ci, load_results  # noqa: E402

OUT = ROOT / "docs" / "figures"
NAVY, AMBER, TEAL = "#0B1B2B", "#FFB020", "#19C2A0"
INK, MUTED, GRID = "#0B1B2B", "#5B6B7A", "#E3E8EC"
SLATE = "#8A9AA8"  # baselines and non-final Najda arms; the final system is the only teal mark

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 20, "axes.titlesize": 26, "axes.titleweight": "bold",
    "axes.labelsize": 22, "xtick.labelsize": 20, "ytick.labelsize": 20, "legend.fontsize": 20,
    "axes.edgecolor": GRID, "axes.linewidth": 1.2, "axes.spines.top": False, "axes.spines.right": False,
    "xtick.color": INK, "ytick.color": INK, "text.color": INK, "axes.labelcolor": INK,
    "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
})

# Run ids are the ones logged in docs/RESULTS.md and docs/PREREGISTRATION.md.
CONFIRM = [  # fresh unseen-family instances (heldout-confirm, 25 incidents, seeds 6001..6025)
    ("single_llm\n(one Sonnet call)", "1031-030410_single_llm_heldout_confirm", SLATE),
    ("Najda v5", "1031-030553_najda_v5_heldout_confirm", SLATE),
    ("Najda v6\n(final)", "1031-030851_najda_v6_heldout_confirm", TEAL),
    ("Najda v6\nHaiku big model", "1031-031108_najda_v6_heldout_confirm", AMBER),
]
JOURNEY = {  # pre-registered journey: dev -> held-out once -> confirmation on new seeds
    "Dev (42)\ntuned here": [("single_llm", "1030-175813_single_llm_dev", SLATE), ("v5", "1030-210840_najda_v5_dev", SLATE)],
    "Held-out (25)\nrun once, pre-registered": [
        ("single_llm", "1030-213142_single_llm_heldout", SLATE), ("v5", "1030-213322_najda_v5_heldout", SLATE),
        ("v5 minus\ndiff_diag", "1030-213735_najda_v5_no_diffdiag_heldout", AMBER),
    ],
    "Confirm (25)\nnew seeds, v6 picked before": [
        ("single_llm", "1031-030410_single_llm_heldout_confirm", SLATE), ("v5", "1031-030553_najda_v5_heldout_confirm", SLATE),
        ("v6", "1031-030851_najda_v6_heldout_confirm", TEAL),
    ],
}
HELDOUT_ABLATIONS = [  # every pre-registered held-out arm with an LLM in it (decision 55)
    ("single_llm (one call)", "1030-213142_single_llm_heldout", SLATE),
    ("v5 COLD (memory off)", "1030-213322_najda_v5_heldout", SLATE),
    ("v5 ONLINE (memory on)", "1030-213621_najda_v5_heldout", SLATE),
    ("v5 minus bisect", "1030-214009_najda_v5_no_bisect_heldout", SLATE),
    ("v5 minus diff_diagnosis (= v6)", "1030-213735_najda_v5_no_diffdiag_heldout", TEAL),
    ("v5, Haiku big model", "1030-214211_najda_v5_heldout", AMBER),
]
MODEL_SWAP = [  # (set, Sonnet run, Haiku run)
    ("Dev, v4", "1030-202319_najda_v4_dev", "1030-203751_najda_v4_dev"),
    ("Held-out, v5", "1030-213322_najda_v5_heldout", "1030-214211_najda_v5_heldout"),
    ("Transfer (Hajz), v5", "1030-214741_najda_v5_transfer", "1030-215005_najda_v5_transfer"),
    ("Confirm, v6", "1031-030851_najda_v6_heldout_confirm", "1031-031108_najda_v6_heldout_confirm"),
]
CURVE = ROOT / "experiments" / "learning_curve" / "1030-194212_najda_v4" / "curve.csv"


def stats(run_id: str) -> dict:
    rows = load_results(run_id)
    if not rows:
        raise SystemExit(f"missing results for {run_id}")
    ok = [bool(r["scores"]["outcome_correct"]) for r in rows]
    lo, hi = bootstrap_ci(ok)
    cost = sum(r["scores"]["cost_usd"] for r in rows) / len(rows)
    return {"n": len(rows), "acc": sum(ok) / len(ok), "lo": lo, "hi": hi, "cost": cost,
            "dangerous": sum(r["scores"]["dangerous_actions"] for r in rows)}


def new_fig(title: str, subtitle: str, ncols: int = 1, widths: list[float] | None = None):
    fig, axes = plt.subplots(1, ncols, figsize=(19.2, 10.8), gridspec_kw={"width_ratios": widths} if widths else None)
    title_lines = textwrap.wrap(title, 60)
    sub_lines = textwrap.wrap(subtitle, 118)
    top = 0.965
    fig.text(0.07, top, "\n".join(title_lines), fontsize=32, fontweight="bold", color=INK, ha="left", va="top", linespacing=1.15)
    top -= 0.052 * len(title_lines) + 0.012
    fig.text(0.07, top, "\n".join(sub_lines), fontsize=20, color=MUTED, ha="left", va="top", linespacing=1.3)
    top -= 0.034 * len(sub_lines) + 0.07
    fig.subplots_adjust(top=top, bottom=0.18, left=0.07, right=0.97, wspace=0.28)
    return fig, (axes if ncols > 1 else [axes])


def footer(fig, text: str) -> None:
    fig.text(0.07, 0.025, "\n".join(textwrap.wrap(text, 135)), fontsize=17, color=MUTED, va="bottom", linespacing=1.3)


def style(ax, ylabel: str = "", ymax: float | None = None):
    ax.grid(axis="y", color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    if ylabel:
        ax.set_ylabel(ylabel)
    if ymax is not None:
        ax.set_ylim(0, ymax)


def bars_with_ci(ax, labels: list[str], st: list[dict], colors: list[str], fmt: str = "{:.2f}", width: float = 0.6):
    xs = list(range(len(labels)))
    ax.bar(xs, [s["acc"] for s in st], width=width, color=colors, zorder=2)
    ax.errorbar(xs, [s["acc"] for s in st], yerr=[[s["acc"] - s["lo"] for s in st], [s["hi"] - s["acc"] for s in st]],
                fmt="none", ecolor=INK, elinewidth=2, capsize=8, capthick=2, zorder=3)
    for x, s in zip(xs, st):
        ax.text(x, s["hi"] + 0.025, fmt.format(s["acc"]), ha="center", va="bottom", fontsize=22, fontweight="bold")
    ax.set_xticks(xs, labels)


def save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.png", dpi=100)
    fig.savefig(OUT / f"{name}.svg")
    plt.close(fig)
    print(f"wrote docs/figures/{name}.png + .svg")


def fig_headline() -> None:
    st = [stats(r) for _, r, _ in CONFIRM]
    n = st[0]["n"]
    fig, (ax1, ax2) = new_fig(
        "Fresh unseen faults: Najda v6 is ahead of a single LLM call, at a similar price",
        f"heldout-confirm set, {n} incidents of held-out fault families with new seeds, pre-registered, run once. "
        "Error bars: 95% bootstrap CI (they overlap at n = 25).", ncols=2, widths=[1.3, 1])
    bars_with_ci(ax1, [l for l, _, _ in CONFIRM], st, [c for _, _, c in CONFIRM])
    style(ax1, "Outcome correct (fixed, or escalated correctly)", 1.12)
    ax1.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax1.set_title("Accuracy on unseen faults", loc="left")
    ax2.bar(range(len(st)), [s["cost"] for s in st], width=0.6, color=[c for _, _, c in CONFIRM], zorder=2)
    for x, s in enumerate(st):
        ax2.text(x, s["cost"] + 0.0008, f"${s['cost']:.4f}", ha="center", va="bottom", fontsize=22, fontweight="bold")
    ax2.set_xticks(range(len(st)), [l for l, _, _ in CONFIRM])
    style(ax2, "USD per incident (list prices)", max(s["cost"] for s in st) * 1.25)
    ax2.set_title("Cost per incident", loc="left")
    footer(fig, f"Dangerous actions: {sum(s['dangerous'] for s in st)} across all four arms. "
           "Runs 1031-030410, 1031-030553, 1031-030851, 1031-031108.")
    save(fig, "headline_confirm")


def fig_journey() -> None:
    fig, (ax,) = new_fig(
        "The pre-registered journey: tuned on dev, held-out run once, confirmed on new seeds",
        "Outcome correct with 95% bootstrap CI. The held-out ablation 'v5 minus diff_diagnosis' beat v5, so it was "
        "named v6 and scored again on fresh instances.")
    x, ticks, labels, pos = 0.0, [], [], []
    for group, arms in JOURNEY.items():
        start = x
        for name, run, color in arms:
            s = stats(run)
            ax.bar(x, s["acc"], width=0.8, color=color, zorder=2)
            ax.errorbar(x, s["acc"], yerr=[[s["acc"] - s["lo"]], [s["hi"] - s["acc"]]], fmt="none", ecolor=INK,
                        elinewidth=2, capsize=8, capthick=2, zorder=3)
            ax.text(x, s["hi"] + 0.02, f"{s['acc']:.2f}", ha="center", va="bottom", fontsize=21, fontweight="bold")
            ax.text(x, -0.03, name, ha="center", va="top", fontsize=18)
            x += 1
        pos.append((start + x - 1) / 2)
        labels.append(group)
        x += 1.2
    ax.set_xticks(pos, labels)
    ax.tick_params(axis="x", pad=72)
    style(ax, "Outcome correct", 1.3)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    fig.subplots_adjust(bottom=0.22)
    ax.legend(handles=[Line2D([], [], marker="s", color=SLATE, ls="", ms=18, label="baseline / earlier Najda"),
                       Line2D([], [], marker="s", color=AMBER, ls="", ms=18, label="ablation arm that reversed H4"),
                       Line2D([], [], marker="s", color=TEAL, ls="", ms=18, label="Najda v6 (final)")],
              loc="upper left", frameon=False, ncol=3)
    save(fig, "journey")


def read_curve() -> dict[str, list[list[float]]]:
    """Per arm, one list of per-incident costs per seed, in stream order."""
    streams: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in csv.DictReader(CURVE.open()):
        streams[(r["arm"], r["seed"])].append(float(r["cost_usd"]))
    out: dict[str, list[list[float]]] = defaultdict(list)
    for (arm, _), xs in sorted(streams.items()):
        out[arm].append(xs)
    return out


def moving_avg(xs: list[float], k: int = 5) -> list[float | None]:
    return [None if i + 1 < min(k, 3) else sum(xs[max(0, i - k + 1): i + 1]) / len(xs[max(0, i - k + 1): i + 1])
            for i in range(len(xs))]


def fig_learning_curve() -> None:
    curves = read_curve()
    off, on = curves["off"][0], curves["on"]
    n = len(off)
    on_mean = [sum(seed[i] for seed in on) / len(on) for i in range(n)]
    fig, (ax1, ax2) = new_fig(
        "Memory: the same 42 dev incidents cost 40% less once Najda has learned the fixes",
        "najda_v4 on a shuffled dev stream. Memory ON = playbooks learned from its own verified fixes during the "
        "stream, mean of 3 orderings; accuracy 0.976 vs 0.968.", ncols=2, widths=[1.3, 1])
    xs = list(range(1, n + 1))
    ax1.plot(xs, moving_avg(off), color=SLATE, lw=3, label="memory OFF")
    ax1.plot(xs, moving_avg(on_mean), color=TEAL, lw=3, label="memory ON (mean of 3 orders)")
    ax1.text(n + 0.4, moving_avg(off)[-1], "OFF", color=SLATE, fontsize=20, fontweight="bold", va="center")
    ax1.text(n + 0.4, moving_avg(on_mean)[-1], "ON", color=TEAL, fontsize=20, fontweight="bold", va="center")
    style(ax1, "USD per incident, 5-incident moving average")
    ax1.set_xlabel("Incident number in the stream")
    ax1.set_xlim(1, n + 3)
    ax1.set_title("Cost per incident falls as playbooks accumulate", loc="left")
    ax1.legend(frameon=False, loc="upper right")
    cum = lambda xs: [sum(xs[: i + 1]) for i in range(len(xs))]  # noqa: E731
    ax2.plot(xs, cum(off), color=SLATE, lw=3)
    ax2.plot(xs, cum(on_mean), color=TEAL, lw=3)
    ax2.text(n + 0.8, cum(off)[-1], f"${cum(off)[-1]:.2f} OFF", color=SLATE, fontsize=22, fontweight="bold", va="center")
    ax2.text(n + 0.8, cum(on_mean)[-1], f"${cum(on_mean)[-1]:.2f} ON", color=TEAL, fontsize=22, fontweight="bold", va="center")
    ax2.set_xlim(0, n + 12)
    style(ax2, "Cumulative USD")
    ax2.set_xlabel("Incident number in the stream")
    ax2.set_title("Whole stream", loc="left")
    footer(fig, "Source: experiments/learning_curve/1030-194212_najda_v4/curve.csv (runs 1030-194212, -194214, -194215, "
           "-194216). 63 of 126 memory-ON incidents needed zero LLM calls; 0 false matches.")
    save(fig, "learning_curve")


def fig_ablations() -> None:
    st = [stats(r) for _, r, _ in HELDOUT_ABLATIONS]
    fig, (ax,) = new_fig(
        "Held-out ablations: what each component bought on unseen faults (run once)",
        "25 held-out incidents, every arm pre-registered before the run. Removing diff_diagnosis helped; bisect "
        "and memory changed nothing or lost one incident.")
    ys = list(range(len(st)))[::-1]
    ax.barh(ys, [s["acc"] for s in st], height=0.6, color=[c for _, _, c in HELDOUT_ABLATIONS], zorder=2)
    ax.errorbar([s["acc"] for s in st], ys, xerr=[[s["acc"] - s["lo"] for s in st], [s["hi"] - s["acc"] for s in st]],
                fmt="none", ecolor=INK, elinewidth=2, capsize=8, capthick=2, zorder=3)
    for y, s in zip(ys, st):
        ax.text(s["hi"] + 0.015, y, f"{s['acc']:.2f}   ${s['cost']:.4f}/incident", va="center", fontsize=21, fontweight="bold")
    ax.set_yticks(ys, [l for l, _, _ in HELDOUT_ABLATIONS])
    ax.set_xlim(0, 1.5)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.grid(axis="x", color=GRID)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    ax.set_xlabel("Outcome correct, 95% bootstrap CI")
    fig.subplots_adjust(left=0.27)
    footer(fig, "Dev ablations (42 incidents, docs/RESULTS.md): diff_diagnosis, guardrails, canary and bisect changed no "
           "dev outcome; code rules bought 1 incident; triage cut cost 22%.")
    save(fig, "ablations_heldout")


def fig_model_swap() -> None:
    fig, (ax,) = new_fig(
        "Haiku vs Sonnet as the investigator: 9 to 12x cheaper, 0 to 12 points less accurate",
        "Same Najda code, only the big model swapped (configs/models_haiku_big.json). Patient and triage stay on "
        "Haiku 5.5. Zero dangerous actions in every run.")
    for name, son, hai in MODEL_SWAP:
        s, h = stats(son), stats(hai)
        ax.plot([h["cost"], s["cost"]], [h["acc"], s["acc"]], color=GRID, lw=2.5, zorder=1)
        ax.scatter([s["cost"]], [s["acc"]], s=420, color=TEAL, zorder=3, edgecolor="white", linewidth=2)
        ax.scatter([h["cost"]], [h["acc"]], s=420, color=AMBER, zorder=3, edgecolor="white", linewidth=2)
        ax.annotate(name, (s["cost"], s["acc"]), xytext=(14, 0), textcoords="offset points", fontsize=19, va="center")
        ax.annotate(f"{h['acc']:.2f}", (h["cost"], h["acc"]), xytext=(-14, 0), textcoords="offset points",
                    fontsize=19, va="center", ha="right")
        ax.annotate(f"{s['acc']:.2f}", (s["cost"], s["acc"]), xytext=(0, 16), textcoords="offset points",
                    fontsize=19, ha="center")
    ax.set_xscale("log")
    ax.set_xticks([0.002, 0.005, 0.01, 0.02, 0.05], ["$0.002", "$0.005", "$0.01", "$0.02", "$0.05"])
    ax.set_xlim(0.0018, 0.06)
    ax.xaxis.set_minor_locator(matplotlib.ticker.NullLocator())
    ax.set_ylim(0.5, 1.05)
    ax.grid(color=GRID)
    ax.set_axisbelow(True)
    ax.tick_params(length=0)
    ax.set_xlabel("USD per incident (log scale)")
    ax.set_ylabel("Outcome correct")
    ax.legend(handles=[Line2D([], [], marker="o", color=TEAL, ls="", ms=18, label="Sonnet 5.5 as big model"),
                       Line2D([], [], marker="o", color=AMBER, ls="", ms=18, label="Haiku 5.5 as big model")],
              loc="lower right", frameon=False)
    footer(fig, "Runs: dev 1030-202319 / 1030-203751; held-out 1030-213322 / 1030-214211; transfer 1030-214741 / "
           "1030-215005; confirm 1031-030851 / 1031-031108.")
    save(fig, "haiku_vs_sonnet")


if __name__ == "__main__":
    fig_headline()
    fig_journey()
    fig_learning_curve()
    fig_ablations()
    fig_model_swap()
