#!/usr/bin/env bash
# Step 7 pre-registered confirmation run (docs/PREREGISTRATION.md, "Step 7"). One pass, results as they come,
# live spend checks; stops before the arm that would push real spend over the $3 cap.
set -u
cd "$(dirname "$0")/.."
SINCE="2026-10-31 02:50"
BUDGET=3
NOTE="step 7 pre-registered confirmation run (docs/PREREGISTRATION.md, tag confirm-v1)"
HC="--split heldout_confirm --bench-dir data/incidents_confirm"
TC="--split transfer_confirm --bench-dir data/incidents_transfer_confirm"
# label | planned $ for this arm and everything after it | command
ARMS=(
  "C-1 single_llm heldout-confirm|2.74|eval/run_bench.py --doctor single_llm $HC"
  "C-2 najda_v5 heldout-confirm|2.28|eval/run_bench.py --doctor najda_v5 $HC"
  "C-3 najda_v6 heldout-confirm|1.54|eval/run_bench.py --doctor najda_v6 $HC"
  "C-4 najda_v6 haiku heldout-confirm|0.90|eval/run_bench.py --doctor najda_v6 $HC --models configs/models_haiku_big.json"
  "C-5 najda_v5 transfer-confirm|0.82|eval/run_bench.py --doctor najda_v5 $TC"
  "C-6 najda_v6 transfer-confirm|0.41|eval/run_bench.py --doctor najda_v6 $TC"
)
for arm in "${ARMS[@]}"; do
  IFS='|' read -r label planned cmd <<< "$arm"
  if ! python scripts/spend.py --since "$SINCE" --budget "$BUDGET" --planned "$planned"; then
    echo "STOPPED before arm '$label': projected spend over budget. Ask before continuing."; exit 1
  fi
  echo "=== $label  ($(TZ=Asia/Riyadh date '+%H:%M:%S') KSA)"
  python $cmd --note "$NOTE: $label" | head -n 2
done
python scripts/spend.py --since "$SINCE" --budget "$BUDGET"
