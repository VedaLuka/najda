# CLAUDE.md — rules for Claude Code in this repo

This is a 2-day hackathon repo judged on: task performance on unseen tests, robustness,
evaluation & iteration, technical judgment, engineering quality, communication.

## Non-negotiable workflow
1. **Baseline first.** No clever system until `baseline_*` and `llm_zero_shot` have dev scores in `experiments/log.jsonl`.
2. **Every change = new named system** in `src/hack/systems.py` (copy, rename, register). Never silently edit a system that already has logged results.
3. **Every new system gets evaluated** with `python eval/run_eval.py --system <name> --split dev --note "<what changed and why>"` before moving on. Then run `scripts/compare.py latest:<previous_best> latest:<new>` and report fixed/broken counts.
4. **One change at a time** where possible, so each gain is attributable (ablations).
5. **Holdout split is for milestones only.** Never tune on it. Never look at holdout examples to write prompts.
6. **Record decisions** in `docs/DECISIONS.md` (one line each: decision, alternatives, evidence/run_id).
7. **Tests stay green**: `python -m pytest -q`. Add a test for every bug fixed.
8. **All LLM calls go through `hack.llm.call_llm`** (cached, reproducible, token-counted). Temperature 0 unless there's a logged reason.

## Style
- Plain, readable Python. Small functions. Type hints. No dead code or commented-out experiments.
- Pin any new dependency in requirements.txt.
- Never commit `.env` or organiser data (NDA).

## When asked "what next?"
Look at `python scripts/report.py` and the BROKEN examples from the last compare, group the
errors into 2-4 types, and propose the change that fixes the biggest group.
