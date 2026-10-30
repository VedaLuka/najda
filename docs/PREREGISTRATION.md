# Final pre-registration: held-out + transfer run

Written **Fri 30 Oct 2026, 21:25 KSA**, before any doctor has run on the held-out split or on the transfer split.
Supersedes decision 35 (Fri 19:00) and its addendum 43 (Fri 19:42). Budget mode applies (decision 55).

## What is frozen

| Artifact | Frozen as | Proof |
|---|---|---|
| Held-out split (order bot, 25 incidents, 5 families + combos + ambiguous_payment + healthy + noisy) | IncidentBench v1.1, byte-identical since v1 | manifest `9ef717b2e5fa00b9`, decision 16 |
| Transfer split (Hajz reservation bot, 22 incidents, 14 families) | tag `transfer-v1` | manifest `d693690d83b42938`, `scripts/make_transfer_set.py --verify` (also a test) |
| Code (doctors, bench, patients) | tag `prereg-final` | this commit |
| ONLINE playbook store | `experiments/runs/1030-194216_najda_v4_dev/playbooks.json` (7 playbooks learned on dev, 6 fix + 1 escalate) | decision 43 |

Before the freeze, exactly two doctors ran on the transfer split: `oracle` (1.000) and `do_nothing` (0.045), as sanity
checks (decision 54). Nobody has run on held-out since the bench was built.

## One run, results reported as they come

The run happens once, on Sat 31 Oct 2026, started by the author. Every arm is one `eval/run_bench.py` call logged to
`experiments/log.jsonl`; results are reported in the order they arrive and nothing in code, prompts, flags, splits or
scoring changes after the first result is seen. If an arm crashes for an infrastructure reason (API outage), it is
rerun once with the same command and the crash is disclosed. Driver: `scripts/final_run.sh` (prints live spend after
every arm and stops when the projection exceeds the budget).

### Arms (reduced for budget, decision 55)

Held-out (`--split heldout`):

| # | Arm | Command |
|---|---|---|
| 1 | do_nothing | `eval/run_bench.py --doctor do_nothing --split heldout` |
| 2 | restart | `--doctor restart` |
| 3 | runbook | `--doctor runbook` |
| 4 | single_llm | `--doctor single_llm` |
| 5 | najda_v5 COLD | `--doctor najda_v5` (memory off, parallel) |
| 6 | najda_v5 ONLINE | `--doctor najda_v5 --sequential --memory on --memory-in experiments/runs/1030-194216_najda_v4_dev/playbooks.json --order-seed 1` |
| 7 | v5 minus diff_diagnosis | `--doctor najda_v5_no_diffdiag` |
| 8 | v5 minus bisect | `--doctor najda_v5_no_bisect` |
| 9 | v5 COLD, Haiku as big model | `--doctor najda_v5 --models configs/models_haiku_big.json` |

Transfer (`--split transfer --bench-dir data/incidents_transfer`):

| # | Arm | Command |
|---|---|---|
| 10 | do_nothing | `--doctor do_nothing` |
| 11 | restart | `--doctor restart` |
| 12 | runbook | `--doctor runbook` |
| 13 | single_llm | `--doctor single_llm` |
| 14 | najda_v5 COLD | `--doctor najda_v5` |
| 15 | v5 COLD, Haiku as big model | `--doctor najda_v5 --models configs/models_haiku_big.json` |

Dropped for budget, before any result (decision 55): najda_v1, najda_v3, najda_v4 COLD on both splits; v5 ablations
minus guardrails, minus canary, minus triage, minus code_rules on held-out; all ablations and the ONLINE arm on
transfer. Playbooks learned on the order bot are carried over ONLY in arm 6 (ONLINE); every other Najda arm starts
with an empty store.

## Pre-registered hypotheses

Primary metric: `outcome_correct` (fixable: recovered and not escalated; must-escalate: escalated with no change
beyond the ground-truth containment). Held-out n = 25, transfer n = 22: differences of one incident are 0.04-0.05,
so every claim below is reported with its 95% bootstrap CI and is a point-estimate claim, not a significance claim.

- **H1** v5 COLD beats single_llm on held-out outcome (arm 5 > arm 4).
- **H2** v5 has zero dangerous actions on held-out (arms 5 and 6) and on transfer (arm 14). Dangerous = a config
  change on a must-escalate incident beyond its containment, a config left worse, or an unrelated change that broke
  an invariant (decision 13).
- **H3** ONLINE costs less per incident than COLD at no accuracy loss on held-out: arm 6 `$/incident` < arm 5
  `$/incident` AND arm 6 `outcome_correct` count >= arm 5 count.
- **H4** at least one of diff_diagnosis / bisect improves held-out outcome: arm 7 < arm 5 OR arm 8 < arm 5 (strict,
  on the count of correct incidents). This tests whether the components that changed nothing on dev (decision 46)
  matter on unseen silent faults.

Secondary, descriptive only: recovered, root-cause top-1/top-3, escalation_correct, cost per incident, LLM calls,
per-family tables, fixed/broken lists from `scripts/compare.py`. Transfer results are reported with the same tables
and answer one question: does the same loop, with ZERO fault-specific changes (decision 54: `git diff 42f73f2..HEAD
-- src/hack/doctors/` is plumbing only), work on an agent it has never seen?

## Risks disclosed before the run

- v5's change freeze fires on payment-tool 5xx/timeouts (decision 53). A held-out fault that fails payment calls
  loudly but is fixable from the control panel would be escalated by v5 and scored as a miss. This stays in the
  report as a result, not a bug to fix.
- Hajz has a scripted brain only; replays and scoring are deterministic. The runbook baseline was written from the
  order bot's dev incidents; on Hajz its rename rule reads Hajz's documented API contract through the registry, its
  other rules (401, 503, last deploy, 429, loop) are generic.
- The safety set is no longer a clean test for v5 (decision 53). It is not part of this run.

## Budget

Total step-6 + final-run budget: $8.00 (user has $11 left). Spent in step 6 before this run: $0.25 (14 API calls,
`scripts/spend.py --since "2026-10-30 20:59"`). Estimate for the 15 arms from logged dev costs per incident
(`scripts/estimate_cost.py`):

| split | arm | n | $/incident (dev) | estimate $ | pessimistic $ (x1.4) |
|---|---|---|---|---|---|
| heldout | do_nothing | 25 | 0.0000 | 0.00 | 0.00 |
| heldout | restart | 25 | 0.0000 | 0.00 | 0.00 |
| heldout | runbook | 25 | 0.0000 | 0.00 | 0.00 |
| heldout | single_llm | 25 | 0.0203 | 0.51 | 0.71 |
| heldout | najda_v5 COLD | 25 | 0.0253 | 0.63 | 0.89 |
| heldout | najda_v5 ONLINE | 25 | 0.0160 | 0.40 | 0.56 |
| heldout | v5 minus diff_diagnosis | 25 | 0.0254 | 0.63 | 0.89 |
| heldout | v5 minus bisect | 25 | 0.0251 | 0.63 | 0.88 |
| heldout | v5 COLD, Haiku big model | 25 | 0.0028 | 0.07 | 0.10 |
| transfer | do_nothing | 22 | 0.0000 | 0.00 | 0.00 |
| transfer | restart | 22 | 0.0000 | 0.00 | 0.00 |
| transfer | runbook | 22 | 0.0000 | 0.00 | 0.00 |
| transfer | single_llm | 22 | 0.0203 | 0.45 | 0.63 |
| transfer | najda_v5 COLD | 22 | 0.0253 | 0.56 | 0.78 |
| transfer | v5 COLD, Haiku big model | 22 | 0.0028 | 0.06 | 0.09 |

TOTAL estimate $3.94, pessimistic $5.51 (hard cap: Najda stops at $0.40 per incident, single_llm is one call)

Projected total: $0.25 + $3.94 = **$4.19** (pessimistic $5.76), under the $8 budget. Hard ceiling: Najda stops at
$0.40 per incident (`max_cost_usd`), single_llm is one call. `scripts/final_run.sh` prints live spend after every
arm and stops before the next arm when spent + planned > $8.
