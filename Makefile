PY ?= python3
SYS ?= baseline_majority
CFG ?=
NOTE ?=
CFG_ARG = $(if $(CFG),--config $(CFG),)

.PHONY: setup smoke split eval robust holdout compare report test

setup:            ## create venv and install deps
	$(PY) -m venv .venv && .venv/bin/pip install -q -r requirements.txt
	@test -f .env || cp .env.example .env
	@echo "Now: source .venv/bin/activate && edit .env"

smoke:            ## end-to-end check on the toy data (no API key needed)
	$(PY) scripts/split_data.py data/sample_raw.jsonl --stratify --out data/_smoke
	$(PY) eval/run_eval.py --system baseline_majority --data-dir data/_smoke --note smoke
	$(PY) eval/run_eval.py --system baseline_echo --data-dir data/_smoke --robustness --note smoke
	$(PY) scripts/report.py

split:            ## make train/dev/holdout: make split RAW=data/raw.jsonl
	$(PY) scripts/split_data.py $(RAW) --stratify

eval:             ## make eval SYS=v2_fewshot CFG=configs/v2.json NOTE="added 5 examples"
	$(PY) eval/run_eval.py --system $(SYS) $(CFG_ARG) --split dev --note "$(NOTE)"

robust:           ## make robust SYS=v2_fewshot
	$(PY) eval/run_eval.py --system $(SYS) $(CFG_ARG) --split dev --robustness --note "$(NOTE)"

holdout:          ## milestones only
	$(PY) eval/run_eval.py --system $(SYS) $(CFG_ARG) --split holdout --note "$(NOTE)"

compare:          ## make compare OLD=latest:baseline_majority NEW=latest:v2_fewshot
	$(PY) scripts/compare.py $(OLD) $(NEW)

report:
	$(PY) scripts/report.py --write

test:
	$(PY) -m pytest -q
