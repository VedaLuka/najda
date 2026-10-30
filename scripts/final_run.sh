#!/usr/bin/env bash
# The pre-registered final run (docs/PREREGISTRATION.md). One pass, results as they come, live spend checks.
#   bash scripts/final_run.sh            # runs every arm in order
# Stops before the next arm when (spent since step-6 start + planned remaining) exceeds the budget.
set -u
cd "$(dirname "$0")/.."
SINCE="2026-10-30 20:59"
BUDGET=8
STORE=experiments/runs/1030-194216_najda_v4_dev/playbooks.json
NOTE="pre-registered final run (docs/PREREGISTRATION.md, tag prereg-final)"
# label | pessimistic $ for this arm and everything after it | command
ARMS=(
  "H1 do_nothing|5.76|eval/run_bench.py --doctor do_nothing --split heldout"
  "H2 restart|5.76|eval/run_bench.py --doctor restart --split heldout"
  "H3 runbook|5.76|eval/run_bench.py --doctor runbook --split heldout"
  "H4 single_llm|5.76|eval/run_bench.py --doctor single_llm --split heldout"
  "H5 najda_v5 COLD|5.05|eval/run_bench.py --doctor najda_v5 --split heldout"
  "H6 najda_v5 ONLINE|4.16|eval/run_bench.py --doctor najda_v5 --split heldout --sequential --memory on --memory-in $STORE --order-seed 1"
  "H7 v5 no_diffdiag|3.60|eval/run_bench.py --doctor najda_v5_no_diffdiag --split heldout"
  "H8 v5 no_bisect|2.71|eval/run_bench.py --doctor najda_v5_no_bisect --split heldout"
  "H9 v5 haiku big|1.83|eval/run_bench.py --doctor najda_v5 --split heldout --models configs/models_haiku_big.json"
  "T10 do_nothing|1.73|eval/run_bench.py --doctor do_nothing --split transfer --bench-dir data/incidents_transfer"
  "T11 restart|1.73|eval/run_bench.py --doctor restart --split transfer --bench-dir data/incidents_transfer"
  "T12 runbook|1.73|eval/run_bench.py --doctor runbook --split transfer --bench-dir data/incidents_transfer"
  "T13 single_llm|1.73|eval/run_bench.py --doctor single_llm --split transfer --bench-dir data/incidents_transfer"
  "T14 najda_v5 COLD|1.10|eval/run_bench.py --doctor najda_v5 --split transfer --bench-dir data/incidents_transfer"
  "T15 v5 haiku big|0.32|eval/run_bench.py --doctor najda_v5 --split transfer --bench-dir data/incidents_transfer --models configs/models_haiku_big.json"
)
for arm in "${ARMS[@]}"; do
  IFS='|' read -r label planned cmd <<< "$arm"
  if ! python scripts/spend.py --since "$SINCE" --budget "$BUDGET" --planned "$planned"; then
    echo "STOPPED before arm '$label': projected spend over budget. Ask before continuing."; exit 1
  fi
  echo "=== $label"
  python $cmd --note "$NOTE: $label" | head -n 2
done
python scripts/spend.py --since "$SINCE" --budget "$BUDGET"
