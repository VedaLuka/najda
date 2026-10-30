# Learning curve: `najda_v4` on dev (memory OFF vs ON)

| arm | seeds | accuracy [95% CI] | $/incident [95% CI] | $/stream | LLM calls/stream | $ first half | $ second half | hits | esc-fast hits | partial hits | false matches | hit rate | false-match rate | zero-LLM incidents |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| off | 1 | 0.976 [0.929, 1.000] | 0.0253 [0.0220, 0.0288] | 1.064 | 118.0 | 0.0222 | 0.0285 | 0 | 0 | 0 | 0 | 0.00 | 0.00 | 2 |
| on | 3 | 0.968 [0.921, 1.000] | 0.0153 [0.0104, 0.0204] | 0.641 | 64.0 | 0.0154 | 0.0151 | 57 | 3 | 9 | 0 | 0.45 | 0.00 | 63 |

Runs: off=1030-193628_najda_v4_dev, on_seed1=1030-193629_najda_v4_dev, on_seed2=1030-193714_najda_v4_dev, on_seed3=1030-193733_najda_v4_dev

Escalate-fast hits are counted apart: an escalation cannot be verified by replay. A partial hit = the playbook's patch was kept as a verified improvement but the incident had a second fault (investigated normally).
