# CLAUDE.md — rules for Claude Code in this repo

This is a 2-day hackathon repo judged on: task performance on unseen tests, robustness,
evaluation & iteration, technical judgment, engineering quality, communication.

## Project: Najda (نجدة) — HUMAIN hackathon, Challenge 1 (Agentic Recovery)
**Pitch:** an AI agent that fixes other AI agents, and gets cheaper every time it learns a fix.
Solo build, deadline Saturday 8pm KSA → favour simple, working, testable code.

Pieces:
- **Patient** (`src/hack/patient/`): a tiny WhatsApp-style order bot (Arabic / English / Saudi
  dialect) over three in-process fake services (OrderAPI, StockAPI, PaymentAPI). Tool loop:
  parse order → check stock → create order → charge → confirm → reply. Two brains behind one
  interface: `scripted` (deterministic, no API key; used by tests/smoke) and `llm` (via
  `hack.llm.call_llm`). Everything Najda may change lives in ONE control panel
  (`patient/config.py::BotConfig`), versioned with history + rollback. Fixes are flat dotted-key
  patches, e.g. `{"retry.max_retries": 3}`.
- **Observability** (`patient/tracing.py`): every chat writes JSONL spans + metrics. Najda sees
  ONLY the incident bundle (traces, metrics, config snapshot, transcripts, invariant violations).
- **Invariants** (`patient/invariants.py`): confirmed ⇒ paid, paid ⇒ confirmed, totals match menu
  SAR, quantities match the customer, turns ≤ hard cap, no unhandled errors. This is how recovery is proven.
- **Fault injector** (`src/hack/faults/catalog.py`): each fault = id, family, description,
  apply(), ground truth (root_cause, correct_fix patch, should_escalate, expected_outcome).
  DEV families: schema_drift, prompt_regression, rate_limit_429, infinite_loop, hallucinated_tool,
  auth_expired_401. HELDOUT families: price_unit_halalas, arabic_numerals, stale_stock,
  dropped_payment_webhook, latency_timeouts. Plus combos, noisy-logs option, must-escalate cases.
- **IncidentBench** (`src/hack/bench/`, `scripts/make_incidents.py`): `data/incidents/{dev,heldout}/<id>/`
  bundles; ground truth lives in `data/incidents/_truth/` which Najda NEVER reads.
  `bench/replay.py::replay(incident_dir, patch)` reruns failed chats and returns pass/fail — Najda's verify step.
- **Najda** (step 2, not built yet): versions are registered systems in `src/hack/systems.py`
  and evaluated on IncidentBench dev.

## Non-negotiable workflow
1. **Baseline first.** No clever Najda until trivial baselines (e.g. `najda_noop`, `najda_rollback_last`)
   and a zero-shot LLM version have dev scores in `experiments/log.jsonl`.
2. **Every change = new named system** in `src/hack/systems.py` (copy, rename, register). Never silently edit a system that already has logged results.
3. **Every new system gets evaluated** with `python eval/run_eval.py --system <name> --split dev --note "<what changed and why>"` before moving on. Then run `scripts/compare.py latest:<previous_best> latest:<new>` and report fixed/broken counts.
4. **One change at a time** where possible, so each gain is attributable (ablations).
5. **Heldout split is for milestones only.** Never tune on it. Never look at heldout incidents or `_truth/` to write prompts.
6. **Record decisions** in `docs/DECISIONS.md` (one line each: decision, alternatives, evidence/run_id).
7. **Tests stay green**: `python -m pytest -q`. Add a test for every bug fixed. `make smoke` must run with no API key.
8. **All LLM calls go through `hack.llm.call_llm`** (cached, reproducible, token-counted). Temperature 0 unless there's a logged reason.
9. **Commands print short summaries only.** Long output (traces, bundles, diffs, full test logs)
   goes to files under `experiments/`, `data/` or the scratchpad; never dump it into the chat.

## Style
- Plain, readable Python. Small functions. Type hints. No dead code or commented-out experiments.
- Stdlib first; pin any new dependency in requirements.txt.
- Never commit `.env` or organiser data (NDA). Synthetic incidents under `data/incidents/` are fine.

## When asked "what next?"
Look at `python scripts/report.py` and the BROKEN incidents from the last compare, group the
errors into 2-4 types, and propose the change that fixes the biggest group.
