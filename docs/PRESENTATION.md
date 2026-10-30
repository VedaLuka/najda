# Presentation outline (aim: 5-7 minutes, 7-8 slides)

Map every slide to a judging criterion. Judges should never have to guess your score.

1. **Problem** (Communication) — the task in one sentence, why it's hard, how it's scored.
2. **Headline result** (Task Performance) — one big number vs the baseline. Bar chart: trivial → zero-shot → final.
3. **Approach** (Technical Judgment) — one pipeline diagram. One line on why not the simpler option.
4. **How I evaluated** (Evaluation & Iteration) — train/dev/holdout, metric, regression checks, N experiments logged.
5. **What actually helped** (Evaluation & Iteration) — ablation table or step chart: each change and its Δ. Include one thing that DIDN'T help and was removed.
6. **Robustness** (Robustness & Adaptation) — score under perturbations / changed requirements; how the system adapts.
7. **Engineering** (Engineering Quality) — repo map, one-command reproduce, tests, cached deterministic runs.
8. **Limitations & next steps** — honest failure examples, what you'd do next.

## Demo (if allowed)
- Pre-record a 60-second backup video. Live demos fail.
- Show one success, one hard case, and the eval command producing the score.

## Prep checklist
- [ ] Numbers on slides match docs/RESULTS.md exactly
- [ ] Rehearsed twice with a timer
- [ ] 3 likely judge questions with answers ready (why this model? cost? what if data shifts?)
