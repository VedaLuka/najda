PY ?= python3
SYS ?= baseline_majority
CFG ?=
NOTE ?=
CFG_ARG = $(if $(CFG),--config $(CFG),)

.PHONY: setup smoke incidents eval holdout compare report test

setup:            ## create venv and install deps
	$(PY) -m venv .venv && .venv/bin/pip install -q -r requirements.txt
	@test -f .env || cp .env.example .env
	@echo "Now: source .venv/bin/activate && edit .env"

smoke:            ## patient bot + fault injector + mini IncidentBench, scripted brain, no API key
	$(PY) -m pytest -q 2>&1 | tail -n 3
	$(PY) scripts/make_incidents.py --small --out data/_smoke
	$(PY) scripts/run_chat.py --fault schema_drift --out experiments/smoke_broken.jsonl | tail -n 2
	$(PY) scripts/run_chat.py --fault schema_drift --fix '{"field_mappings.order_id": "id"}' --out experiments/smoke_fixed.jsonl | tail -n 2

incidents:        ## build the full IncidentBench into data/incidents/
	$(PY) scripts/make_incidents.py

eval:             ## make eval SYS=najda_v2 CFG=configs/v2.json NOTE="what changed"
	$(PY) eval/run_eval.py --system $(SYS) $(CFG_ARG) --split dev --note "$(NOTE)"

holdout:          ## milestones only
	$(PY) eval/run_eval.py --system $(SYS) $(CFG_ARG) --split holdout --note "$(NOTE)"

compare:          ## make compare OLD=latest:najda_v1 NEW=latest:najda_v2
	$(PY) scripts/compare.py $(OLD) $(NEW)

report:
	$(PY) scripts/report.py --write

test:
	$(PY) -m pytest -q
