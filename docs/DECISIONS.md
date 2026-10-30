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
