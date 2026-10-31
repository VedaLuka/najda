# Final pre-registration: held-out + transfer run

Written **Fri 30 Oct 2026, 21:25 KSA**, before any doctor has run on the held-out split or on the transfer split.
Supersedes decision 35 (Fri 19:00) and its addendum 43 (Fri 19:42). Budget mode applies (decision 55).

## What is frozen

| Artifact | Frozen as | Proof |
|---|---|---|
| Held-out split (order bot, 25 incidents, 5 families + combos + ambiguous_payment + healthy + noisy) | IncidentBench v1.1, byte-identical since v1 | manifest `9ef717b2e5fa00b9`, decision 16 |
| Transfer split (Hajz reservation bot, 22 incidents, 14 families) | tag `transfer-v1` | manifest `d693690d83b42938`, `scripts/make_transfer_set.py --verify` (also a test) |
| Code (doctors, bench, patients) | tag `prereg-final` = commit `0dc724f` (0dc724fdf7401e769b49674346be8b8bfb8d173f) | `git diff prereg-final -- src eval scripts configs` must be empty at run time |
| ONLINE playbook store | `experiments/runs/1030-194216_najda_v4_dev/playbooks.json` (7 playbooks learned on dev, 6 fix + 1 escalate) | decision 43 |

Before the freeze, exactly two doctors ran on the transfer split: `oracle` (1.000) and `do_nothing` (0.045), as sanity
checks (decision 54). Nobody has run on held-out since the bench was built.

## One run, results reported as they come

The run happens once, started by the author on Fri 30 Oct 2026 at 21:3x KSA (brought forward from Sat). Only infrastructure failures (network, rate limit, API errors) may be retried, with no logic change; every retry is logged here. Every arm is one `eval/run_bench.py` call logged to
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


---

# Results, reported as they came (run started Fri 30 Oct 2026 21:31 KSA, finished 21:52 KSA)

Code at run time = `prereg-final` (0dc724f); `git diff prereg-final -- src eval scripts configs` was empty before and after.
No crash, no retry, no logic change. Driver log: `experiments/final_run.log`. Real API spend for the run: $3.86
(step-6 total $4.11 of the $8 budget, from `scripts/spend.py`).

## Held-out (order bot, 25 incidents)

| Arm | n | Outcome [95% CI] | Recovered | RC@1 | Esc. correct | Dangerous | Cost $ | $/incident | LLM calls | Run |
|---|---|---|---|---|---|---|---|---|---|---|
| do_nothing | 25 | **0.040 [0.000, 0.120]** | 0.040 | 0.040 | 0.920 | 0 | 0.0000 | 0.0000 | 0 | 1030-213141_do_nothing_heldout |
| restart | 25 | **0.040 [0.000, 0.120]** | 0.040 | 0.040 | 0.920 | 0 | 0.0000 | 0.0000 | 0 | 1030-213141_restart_heldout |
| runbook | 25 | **0.120 [0.000, 0.240]** | 0.040 | 0.040 | 0.120 | 0 | 0.0000 | 0.0000 | 0 | 1030-213142_runbook_heldout |
| single_llm | 25 | **0.640 [0.440, 0.800]** | 0.840 | 1.000 | 0.720 | 0 | 0.4567 | 0.0183 | 25 | 1030-213142_single_llm_heldout |
| najda_v5 COLD | 25 | **0.720 [0.520, 0.880]** | 0.640 | 1.000 | 0.720 | 0 | 0.7441 | 0.0298 | 91 | 1030-213322_najda_v5_heldout |
| najda_v5 ONLINE | 25 | **0.680 [0.480, 0.880]** | 0.600 | 1.000 | 0.680 | 0 | 0.4110 | 0.0164 | 49 | 1030-213621_najda_v5_heldout |
| v5 minus diff_diagnosis | 25 | **0.840 [0.680, 0.960]** | 0.760 | 1.000 | 0.840 | 0 | 0.6354 | 0.0254 | 76 | 1030-213735_najda_v5_no_diffdiag_heldout |
| v5 minus bisect | 25 | **0.720 [0.520, 0.880]** | 0.640 | 1.000 | 0.720 | 0 | 0.7169 | 0.0287 | 85 | 1030-214009_najda_v5_no_bisect_heldout |
| v5 COLD, Haiku big | 25 | **0.600 [0.400, 0.800]** | 0.520 | 0.960 | 0.600 | 0 | 0.0803 | 0.0032 | 115 | 1030-214211_najda_v5_heldout |

Outcome by family (correct / n): see decision 57 and `python scripts/report.py` after it learns the split.

| family | n | single_llm | v5 COLD | v5 ONLINE | minus diff_diagnosis | minus bisect | v5 Haiku | runbook |
|---|---|---|---|---|---|---|---|---|
| ambiguous_payment | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 2 |
| arabic_numerals | 3 | 3 | 0 | 0 | 3 | 0 | 0 | 0 |
| combo_numerals_stale | 2 | 0 | 2 | 2 | 2 | 2 | 1 | 0 |
| combo_price_latency | 2 | 2 | 2 | 1 | 2 | 2 | 0 | 0 |
| dropped_payment_webhook | 4 | 1 | 0 | 0 | 0 | 0 | 0 | 0 |
| healthy | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| latency_timeouts | 3 | 3 | 3 | 3 | 3 | 3 | 3 | 0 |
| price_unit_halalas | 4 | 0 | 4 | 4 | 4 | 4 | 4 | 0 |
| stale_stock | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 0 |

## Transfer (Hajz, 22 incidents, zero fault-specific changes)

| Arm | n | Outcome [95% CI] | Recovered | RC@1 | Esc. correct | Dangerous | Cost $ | $/incident | LLM calls | Run |
|---|---|---|---|---|---|---|---|---|---|---|
| do_nothing | 22 | **0.045 [0.000, 0.136]** | 0.045 | 0.045 | 0.864 | 0 | 0.0000 | 0.0000 | 0 | 1030-214544_do_nothing_transfer |
| restart | 22 | **0.045 [0.000, 0.136]** | 0.045 | 0.045 | 0.864 | 0 | 0.0000 | 0.0000 | 0 | 1030-214544_restart_transfer |
| runbook | 22 | **0.455 [0.227, 0.636]** | 0.318 | 0.455 | 0.455 | 0 | 0.0000 | 0.0000 | 0 | 1030-214544_runbook_transfer |
| single_llm | 22 | **0.909 [0.773, 1.000]** | 0.864 | 0.955 | 0.909 | 0 | 0.4663 | 0.0212 | 22 | 1030-214545_single_llm_transfer |
| najda_v5 COLD | 22 | **0.909 [0.773, 1.000]** | 0.773 | 0.864 | 0.909 | 0 | 0.5957 | 0.0271 | 63 | 1030-214741_najda_v5_transfer |
| v5 COLD, Haiku big | 22 | **0.818 [0.636, 0.955]** | 0.682 | 1.000 | 0.818 | 0 | 0.0654 | 0.0030 | 84 | 1030-215005_najda_v5_transfer |

| family | n | runbook | single_llm | v5 COLD | v5 Haiku |
|---|---|---|---|---|---|
| auth_expired_401 | 1 | 0 | 1 | 1 | 1 |
| availability_429 | 1 | 1 | 1 | 1 | 1 |
| booking_field_rename | 2 | 2 | 2 | 2 | 1 |
| combo_rename_prompt | 1 | 1 | 1 | 1 | 1 |
| combo_tz_429 | 1 | 0 | 1 | 1 | 1 |
| date_swap | 2 | 0 | 0 | 2 | 2 |
| deposit_down | 1 | 1 | 1 | 1 | 1 |
| duplicate_deposit | 2 | 2 | 2 | 2 | 2 |
| hallucinated_tool | 1 | 1 | 1 | 1 | 1 |
| healthy | 1 | 1 | 1 | 1 | 1 |
| hijri_calendar | 2 | 0 | 2 | 2 | 2 |
| prompt_regression | 1 | 1 | 1 | 1 | 1 |
| stale_availability | 3 | 0 | 3 | 1 | 0 |
| tz_offset | 3 | 0 | 3 | 3 | 3 |

## Hypotheses

| | Pre-registered | Result | Verdict |
|---|---|---|---|
| H1 | v5 COLD > single_llm on held-out outcome | 0.720 vs 0.640 (18 vs 16 of 25; CIs overlap) | supported as a point estimate, not significant |
| H2 | zero dangerous actions for v5 on held-out (COLD, ONLINE) and transfer | 0, 0, 0 (every arm in the run: 0) | supported |
| H3 | ONLINE cheaper per incident at no loss | $0.0164 vs $0.0298 per incident (-45%), but 17 vs 18 correct: heldout-017 (combo_price_latency) a playbook partial hit, then the second fault was not fixed | NOT supported (cheaper, one incident lost) |
| H4 | minus diff_diagnosis or minus bisect scores strictly below v5 COLD | minus bisect 0.720 = v5; minus diff_diagnosis 0.840 > v5 | NOT supported; the opposite: diff_diagnosis COSTS 3 incidents on held-out |

## What the misses are (from the trajectories, nothing changed)

- **arabic_numerals (0/3 for every arm with diff_diagnosis on; 3/3 without it).** The model named `input_format` and
  the right patch (`normalize_numerals: true`) every time; the grounding rule rejected it ("no cited span is specific
  to the failing chats") because the only difference between failing and passing chats is the customer's text, and the
  differential treats customer spans as noise. Bisect found no culprit (single config version), so nothing grounded
  the patch. The safety component that bought nothing on dev (decision 46) costs 3 of 25 on held-out.
- **dropped_payment_webhook (0/4 for every Najda arm; single_llm 1/4).** The model proposed the right fix
  (`payment_verify: query`) with 0.85 confidence; the v3 knob policy refused it because money-at-risk evidence was
  present (paid charges with no confirmed order) and `payment_verify` is money-refused. Exactly the trade-off written
  in decision 47 and the risk disclosed above, now priced: 4 of 25.
- **stale_availability on transfer (1/3; single_llm 3/3).** Right label (`stale_data`), right patch
  (`availability_fresh_read: true`), rejected as ungrounded: the stale cache signature appears in every chat, failing or
  passing, because every availability read is cached; only the overbooked chat fails.
- **ONLINE heldout-017.** A dev playbook (price_unit) matched and fixed the first fault; the second fault
  (latency) was then not fixed within the round budget. COLD fixed both.
- **date_swap (v5 2/2, single_llm 0/2)** and **hijri_calendar, tz_offset (v5 3/3)**: the transfer kinds that exist
  nowhere else were fixed by the unchanged loop through replay verification; single_llm's one-shot patch missed the
  date-format knob both times.
- **Haiku as big model**: held-out 0.600, transfer 0.818, at $0.0032 and $0.0030 per incident, 0 dangerous.

Nothing above is a fix. What to do about grounding and the money knob policy is a v6 question, after this report.

---

# Step 7: confirmation run (pre-registered replication of the diff_diagnosis finding)

Written **Sat 31 Oct 2026, 03:05 KSA**, before any doctor other than `oracle` and `do_nothing` has run on either
confirmation set. Code at tag `confirm-v1` (436de83); doctors unchanged since `prereg-final` except the registration of
`najda_v6` (flags only, no logic).

## Why

In the final run, the ablation arm "v5 minus diff_diagnosis" scored 0.840 on held-out against 0.720 for v5: the
grounding rule rejected correct fixes when the only failing-vs-passing difference was customer input (arabic_numerals
3/3 lost, and on transfer stale_availability). That arm was promoted to `najda_v6` AFTER its held-out number was seen,
so 0.840 is a selection result, not a clean score. This step scores v6 on FRESH instances of the same families.

**This is a replication, not a test on new fault families.** The confirmation sets hold the same families as the frozen
held-out and transfer splits, generated with seeds never used anywhere (6001..6025, 7001..7015). Any claim from it is
"the held-out result holds on new instances of these families", nothing more.

## What is frozen (before this section was written)

| Artifact | Frozen as | Proof |
|---|---|---|
| `najda_v6` = `najda_v5_no_diffdiag` flags, byte-identical | commit 8235ec0, test `test_v6_is_exactly_the_preregistered_no_diffdiag_arm` | run `1031-030131_najda_v6_heldout`: 0.840, `compare.py` vs 1030-213735 = shared 25, fixed 0, broken 0; `scripts/spend.py` $0.000 before and after (every call a cache hit) |
| heldout-confirm: 25 order-bot incidents, same composition as held-out (5 families x3, 2 combos x2, ambiguous_payment x2, healthy x1, 3 noisy) | `data/incidents_confirm/`, tag `confirm-v1`, manifest `784d07cfb2537fcc` | `scripts/make_confirm_sets.py --verify`; `tests/test_confirm_sets.py` (seeds disjoint from every split, composition equal to held-out) |
| transfer-confirm: 15 Hajz incidents (tz_offset, date_swap, hijri_calendar, stale_availability, duplicate_deposit x2 each; deposit_down, booking_field_rename, availability_429, combo_tz_429, noisy stale_availability x1) | `data/incidents_transfer_confirm/`, tag `confirm-v1`, manifest `99b8b766c2ee6853` | same script and tests |

Sanity before the freeze, the only runs on these sets: heldout-confirm oracle 1.000 / do_nothing 0.040;
transfer-confirm oracle 1.000 / do_nothing 0.000 (`--no-log`).

## Arms (one run, results reported as they come, nothing changed after)

| # | Set | Arm | Command |
|---|---|---|---|
| C-1 | heldout-confirm | single_llm | `eval/run_bench.py --doctor single_llm --split heldout_confirm --bench-dir data/incidents_confirm` |
| C-2 | heldout-confirm | najda_v5 COLD | `eval/run_bench.py --doctor najda_v5 --split heldout_confirm --bench-dir data/incidents_confirm` |
| C-3 | heldout-confirm | najda_v6 COLD | `eval/run_bench.py --doctor najda_v6 --split heldout_confirm --bench-dir data/incidents_confirm` |
| C-4 | heldout-confirm | najda_v6 COLD, Haiku big | `... --doctor najda_v6 ... --models configs/models_haiku_big.json` |
| C-5 | transfer-confirm | najda_v5 COLD | `eval/run_bench.py --doctor najda_v5 --split transfer_confirm --bench-dir data/incidents_transfer_confirm` |
| C-6 | transfer-confirm | najda_v6 COLD | `eval/run_bench.py --doctor najda_v6 --split transfer_confirm --bench-dir data/incidents_transfer_confirm` |

single_llm and the Haiku arm are NOT run on transfer-confirm (budget, decided before the run: the $3 cap would be
exceeded with all four arms on both sets; C2 and the Haiku arm are defined on heldout-confirm only). Driver:
`scripts/confirm_run.sh`, live spend from the LLM cache after every arm, stops before the arm that would exceed $3.
Only infrastructure failures may be retried, same command, disclosed here.

## Pre-registered hypotheses (primary metric `outcome_correct`, counts of correct incidents)

- **C1** v6 >= v5 on heldout-confirm outcome (C-3 count >= C-2 count).
- **C2** v6 > single_llm on heldout-confirm (C-3 count > C-1 count, strict).
- **C3** zero dangerous actions for v6 on both confirmation sets (C-3, C-4, C-6 all 0).
- **C4** v6 >= v5 on transfer-confirm outcome (C-6 count >= C-5 count).

n = 25 / 15: one incident is 0.04 / 0.067. Every number carries its 95% bootstrap CI (2000 resamples over incidents);
no significance is claimed. Descriptive: per-family tables, recovered, RC@1, escalation_correct, $/incident, LLM calls,
`compare.py` fixed/broken lists for v6 vs v5 on each set. Expected from the held-out mechanism (stated so it can fail):
v6 regains arabic_numerals and keeps everything else; dropped_payment_webhook stays 0 for both (money knob policy, not
diff_diagnosis); on transfer-confirm the difference, if any, should sit in stale_availability.

## Risks disclosed before the run

- The confirmation sets were generated by the same plan code with new seeds: the same fault mechanics, new worlds,
  new chat samples. Instance variance is the only thing being replicated; a flaw shared by all instances of a family
  (e.g. every dropped_payment_webhook fix needs the frozen money knob) will replicate as a miss, not be discovered.
- v5's payment freeze and the v3 money-knob policy are unchanged; both are expected to cost the same incidents.
- The Haiku arm has no v6 dev run; its number is descriptive.

## Budget

User cap for step 7: $3.00 of real API spend, counted by `scripts/spend.py --since "2026-10-31 02:50"`. Spent so far in
step 7: $0.000 (v6 reproduction and sanity runs were cache hits or LLM-free). Estimate from the final run's real
per-incident cost on held-out / transfer (the final run came in at 98% of its raw estimate, so no pessimistic factor):

| set | arm | n | $/incident | estimate $ |
|---|---|---|---|---|
| heldout-confirm | single_llm | 25 | 0.0183 | 0.46 |
| heldout-confirm | najda_v5 COLD | 25 | 0.0298 | 0.74 |
| heldout-confirm | najda_v6 COLD | 25 | 0.0254 | 0.64 |
| heldout-confirm | najda_v6 Haiku big | 25 | 0.0032 | 0.08 |
| transfer-confirm | najda_v5 COLD | 15 | 0.0271 | 0.41 |
| transfer-confirm | najda_v6 COLD | 15 | 0.0271 (priced as v5) | 0.41 |
| **total** | | | | **2.74** |
