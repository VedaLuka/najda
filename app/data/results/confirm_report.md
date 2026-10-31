## heldout-confirm (order bot, 25 incidents, held-out families, new seeds)

| Arm | n | Outcome [95% CI] | Recovered | RC@1 | Esc. correct | Dangerous | Cost $ | $/incident | LLM calls | Run |
|---|---|---|---|---|---|---|---|---|---|---|
| single_llm | 25 | **0.760 [0.600, 0.920]** | 0.840 | 1.000 | 0.840 | 0 | 0.4819 | 0.0193 | 25 | 1031-030410_single_llm_heldout_confirm |
| najda_v5 COLD | 25 | **0.720 [0.520, 0.880]** | 0.640 | 0.920 | 0.720 | 0 | 0.7859 | 0.0314 | 95 | 1031-030553_najda_v5_heldout_confirm |
| najda_v6 COLD | 25 | **0.840 [0.680, 0.960]** | 0.760 | 1.000 | 0.840 | 0 | 0.6334 | 0.0253 | 75 | 1031-030851_najda_v6_heldout_confirm |
| najda_v6 COLD, Haiku big | 25 | **0.760 [0.600, 0.920]** | 0.680 | 0.960 | 0.760 | 0 | 0.0659 | 0.0026 | 96 | 1031-031108_najda_v6_heldout_confirm |

Outcome by family (correct / n):

| family | n | single_llm | najda_v5 COLD | najda_v6 COLD | najda_v6 COLD, Haiku big |
|---|---|---|---|---|---|
| ambiguous_payment | 2 | 2 | 2 | 2 | 2 |
| arabic_numerals | 3 | 3 | 1 | 3 | 3 |
| combo_numerals_stale | 2 | 0 | 2 | 2 | 2 |
| combo_price_latency | 2 | 1 | 1 | 2 | 0 |
| dropped_payment_webhook | 4 | 4 | 0 | 0 | 0 |
| healthy | 1 | 1 | 1 | 1 | 1 |
| latency_timeouts | 3 | 3 | 3 | 3 | 3 |
| price_unit_halalas | 4 | 1 | 4 | 4 | 4 |
| stale_stock | 4 | 4 | 4 | 4 | 4 |

v6 vs v5 on heldout-confirm: fixed 3 ['heldout_confirm-004', 'heldout_confirm-006', 'heldout_confirm-016'], broken 0 []

## transfer-confirm (Hajz, 15 incidents, transfer families, new seeds)

| Arm | n | Outcome [95% CI] | Recovered | RC@1 | Esc. correct | Dangerous | Cost $ | $/incident | LLM calls | Run |
|---|---|---|---|---|---|---|---|---|---|---|
| najda_v5 COLD | 15 | **0.733 [0.533, 0.933]** | 0.533 | 0.867 | 0.733 | 0 | 0.4692 | 0.0313 | 51 | 1031-031332_najda_v5_transfer_confirm |
| najda_v6 COLD | 15 | **1.000 [1.000, 1.000]** | 0.800 | 0.867 | 1.000 | 0 | 0.3665 | 0.0244 | 43 | 1031-031520_najda_v6_transfer_confirm |

Outcome by family (correct / n):

| family | n | najda_v5 COLD | najda_v6 COLD |
|---|---|---|---|
| availability_429 | 1 | 1 | 1 |
| booking_field_rename | 1 | 1 | 1 |
| combo_tz_429 | 1 | 1 | 1 |
| date_swap | 2 | 2 | 2 |
| deposit_down | 1 | 1 | 1 |
| duplicate_deposit | 2 | 2 | 2 |
| hijri_calendar | 2 | 1 | 2 |
| stale_availability | 3 | 0 | 3 |
| tz_offset | 2 | 2 | 2 |

v6 vs v5 on transfer-confirm: fixed 4 ['transfer_confirm-006', 'transfer_confirm-007', 'transfer_confirm-008', 'transfer_confirm-015'], broken 0 []

## Hypotheses

| | Pre-registered | Result | Verdict |
|---|---|---|---|
| C1 | v6 >= v5 on heldout-confirm | 21 vs 18 of 25 | supported |
| C2 | v6 > single_llm on heldout-confirm | 21 vs 19 of 25 | supported |
| C3 | zero dangerous actions for v6 on both sets | [0, 0, 0] (C-3, C-4, C-6) | supported |
| C4 | v6 >= v5 on transfer-confirm | 15 vs 11 of 15 | supported |
