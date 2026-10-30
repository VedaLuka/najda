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
- **Doctors** (`src/hack/doctors/`): any incident-fixing agent. A doctor only sees an `Environment`
  (OTel-shaped traces, metrics, config + history, transcripts, invariants; apply_patch / rollback /
  replay / escalate / llm). Truth files are sealed by an audit hook while doctors run.
  Baselines: `do_nothing`, `restart` (B0), `runbook` (B1, dev rules only), `single_llm` (B2, one
  big-model call). `oracle` reads truth: bench sanity only, never reported as a system.
- **Scorer** (`src/hack/bench/score.py`): the only code that interprets truth. PRIMARY metric =
  `outcome_correct`: fixable → recovered AND NOT escalated; must-escalate → escalated AND no config
  change beyond the ground-truth containment. Transient faults also require a retry (a passing replay).
- **Bench versions:** v1.1 = v1 + `transient_blip` (dev) + auth fix via `auth.key_slot` (dev).
  Heldout is frozen byte-identical since v1; `make_incidents.py` never rebuilds it without `--rebuild-heldout`.
- **Doctor prompts** may use the generic root-cause taxonomy but must contain nothing written for a
  specific held-out family.
- **Models** (`configs/models.json`): provider + model per role (patient, triage, big). Prices in
  `configs/prices.json` (confirmed from the official Anthropic pricing page, 2026-10-30). Cache entries keep original token usage so reruns report real cost.
- **Najda** (`src/hack/doctors/najda/`): `loop.py` = INVESTIGATE (big model, Anthropic tools API over the
  Environment) -> HYPOTHESISE (ranked, taxonomy label + span evidence + confidence + smallest patch) -> FIX
  (one patch at a time, guardrails) -> VERIFY (canary then full replay of failed chats, regression replay of
  passing chats) -> next hypothesis / next fault / ESCALATE. Code decides; the model proposes. Flags:
  `diff_diagnosis` (failing-vs-passing span signatures, grounded hypotheses), `guardrails` (blast radius,
  protected knobs, money-at-risk, auto-rollback), `canary`, `bisect` (config-history binary search by replay).
  `najda_v1` = core loop; `najda_v2` = all flags. Tests use a fake LLM (`tests/test_najda.py`).
- **Najda v4 memory** (`najda/playbooks.py`, flag `playbooks`): after a VERIFIED fix the loop stores a playbook =
  structured signature (failing-only span tokens, violation types, bisect result, money flag; no free text, no ids)
  + patch template parameterised from evidence (`$bisect_old`, `$key_for`, `$status_code`). Matched before any
  big-model call (tier 1 exact, tier 2 Jaccard >= 0.6) and applied through the same guardrails/canary/replay.
  Partial hit (second fault) = investigate normally; failed verify = false match, disabled after 2. Escalate-fast
  playbooks need money-at-risk + exact match and are reported apart. Store lives in `Doctor.memory`, saved to
  `experiments/runs/<run_id>/playbooks.json`; `run_bench.py --sequential --memory on [--memory-in store] [--order-seed k]`.
  `najda_v4_nt` = v3 + playbooks; `najda_v4` = + Haiku triage brief (`najda/triage.py`). Learning curve:
  `scripts/learning_curve.py`; demo: `scripts/demo_repeat.py`. Tests: `tests/test_playbooks.py`.

## Non-negotiable workflow
1. **Baseline first.** No clever Najda until `do_nothing`, `restart`, `runbook` and `single_llm`
   have dev scores in `experiments/log.jsonl`.
2. **Every change = new named doctor** in `src/hack/doctors/` (copy, rename, `@register`). Never silently edit a doctor that already has logged results.
3. **Every new doctor gets evaluated** with `python eval/run_bench.py --doctor <name> --split dev --note "<what changed and why>"` before moving on. Then run `scripts/compare.py latest:<previous_best> latest:<new>` and report fixed/broken counts.
4. **One change at a time** where possible, so each gain is attributable (ablations).
5. **Heldout split is for milestones only.** Never tune on it. Never look at heldout incidents or `_truth/` to write prompts.
6. **Record decisions** in `docs/DECISIONS.md` (one line each: decision, alternatives, evidence/run_id).
   All timestamps (decisions, notes, docs) are KSA time (UTC+3); check `TZ=Asia/Riyadh date` / git log, never guess.
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
