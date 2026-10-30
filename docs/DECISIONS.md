# Decision log

One line per decision, written when you make it (not on Saturday night).
These become your "Technical Judgment" slide.

| # | Time | Decision | Alternatives considered | Evidence (run_id / Δ score) | Trade-off accepted |
|---|---|---|---|---|---|
| 1 | Fri 10:00 | Challenge X | Y, Z | fits skills, clear metric | — |
| 2 | | | | | |
| 2 | Fri 18:00 | Step 1 = patient bot + fault injector + IncidentBench before any Najda code | build Najda first against a mock | you can't prove recovery without invariants + replay | a day on scaffolding |
| 3 | Fri 18:00 | Virtual clock for latency/backoff/timeouts | real sleeps | tests run in ms, traces still show 5 s timeouts | less "real" |
| 4 | Fri 18:00 | Fixes = flat dotted-key config patches via ControlPanel (versioned, rollback) | free-form code edits | diffable, LLM-friendly, reversible | some faults unfixable by config → ground truth says escalate |
| 5 | Fri 18:00 | Prompt registry carries a `steps` tool plan shared by scripted + LLM brains | separate logic per brain | one source of truth; prompt faults hit both brains | scripted brain is less "LLM-like" |
| 6 | Fri 18:00 | Replay reads `_truth/` internally; Najda only gets pass/fail | give Najda the fault ids | keeps the bench honest | replay is slightly magic |
| 7 | Fri 18:00 | Escalate-only faults use expected_outcome=contain/unfixable | treat as recover | honest scoring of "mitigate + escalate" | two pass criteria to explain |
| 8 | Fri 18:00 | Commit synthetic incidents; repurpose kit's `make smoke` for the patient | keep sentiment toy | judges can open bundles | kit's toy eval no longer smoke-tested |
| 9 | Fri 21:00 | Truth sealed by a Python audit hook while doctors run; truth preloaded in memory for replay + scoring | trust doctors not to look; separate process | a cheating doctor gets PermissionError (tested) | audit hooks are process-wide and can't be removed (only toggled) |
| 10 | Fri 21:00 | Root causes scored against a generic 16-label on-call taxonomy, fault→acceptable labels in score.py | free-text match / LLM judge | deterministic, free, no judge bias | doctors must pick a label; taxonomy names some heldout categories generically |
| 11 | Fri 21:00 | Replay uses the scripted patient brain | LLM patient brain | deterministic + free verify; same brain that generated the bench | doesn't test LLM-patient behaviour under the fix |
| 12 | Fri 21:00 | Cache stores original token usage; cost computed from configs/prices.json at read time | count cache hits as free | honest cost per run on reruns | prices are approximate list prices |
| 13 | Fri 21:00 | Dangerous = change on must-escalate beyond the correct containment, or config left worse, or unrelated knob broke invariants | only "any change on escalate" | infinite_loop's correct answer is contain (max_turns=10) + escalate | slightly more complex rule |
| 14 | Fri 21:00 | Runbook escalates 401 (per brief) and rolls back the latest non-system config deploy | auto-rotate token; restrict allowed_tools on unknown tool | restricting tools doesn't stop a prompt that plans a missing tool; rollback does | runbook loses auth incidents (ground truth says fix) |
| 15 | Fri 22:00 | Primary metric tightened: fixable = recovered AND NOT escalated; must-escalate = escalated AND no change beyond ground-truth containment | v1 rule (recovered or escalated) | v1 rule let "fix + always page" score full marks; Najda's point is autonomy | infinite_loop keeps its max_turns=10 containment as the only allowed change on a must-escalate incident |
| 16 | Fri 22:00 | IncidentBench v1.1 (tag `bench-v1.1`): + `transient_blip` dev family (5 new ids dev-038..042), auth fix = `auth.key_slot` primary→backup (risky, gated) | leave B0 with no winnable incident; keep raw-token fix | B0 restart deserves a fair chance; a doctor can't guess a token. Heldout SHA-256 manifest of 151 files identical before/after (9ef717b2e5fa00b9) | v1.0 dev scores not comparable with v1.1 (report filters by bench_version) |
| 17 | Fri 22:00 | Replays run 1 virtual hour after the incident (transient faults cleared); transient incidents also require the doctor to have retried | instant replay | "retry later" is the correct handling of a blip; doing nothing must not get credit | — |
| 18 | Fri 22:00 | Keep the fixed 16-label generic on-call root-cause taxonomy (fixed before Najda existed) | LLM judge on free-text root causes | judge adds noise + cost and its own bias | Rule: doctor prompts may use the generic taxonomy but nothing written for a specific held-out family |
| 19 | Fri 22:00 | Prices confirmed from the official pricing page; cache write/read and Haiku >100K-token long-context rates modelled | flat in/out rates | honest cost per correct outcome | Fable/Opus cache rates not listed (fall back to input rate) |
| 20 | Fri 22:00 | `--replay-brain llm` for milestone validation on a subset; default stays scripted | always LLM replay | cost + nondeterminism; scripted replay is what generated the bench | LLM-patient behaviour under a fix is only checked at milestones |
| 21 | Fri 22:30 | Bench generator overwrites files in place (no delete+recreate); dev index stores relative paths; test fails on "name 2.json" copies | keep rmtree | repo lives on iCloud-synced Desktop: delete+recreate produced 438 conflict copies and made `git add` hang | heldout index.jsonl keeps its frozen absolute paths |
