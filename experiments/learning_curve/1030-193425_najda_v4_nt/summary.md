# Learning curve: `najda_v4_nt` on dev (memory OFF vs ON)

| arm | seeds | accuracy [95% CI] | $/incident [95% CI] | $/stream | LLM calls/stream | $ first half | $ second half | hits | esc-fast hits | partial hits | false matches | hit rate | false-match rate | zero-LLM incidents |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| off | 1 | 0.976 [0.929, 1.000] | 0.0325 [0.0261, 0.0399] | 1.365 | 79.0 | 0.0260 | 0.0390 | 0 | 0 | 0 | 0 | 0.00 | 0.00 | 2 |
| on | 3 | 0.968 [0.921, 1.000] | 0.0204 [0.0129, 0.0287] | 0.855 | 48.0 | 0.0191 | 0.0216 | 57 | 3 | 8 | 0 | 0.45 | 0.00 | 63 |

Runs: off=1030-193425_najda_v4_nt_dev, on_seed1=1030-193426_najda_v4_nt_dev, on_seed2=1030-193517_najda_v4_nt_dev, on_seed3=1030-193535_najda_v4_nt_dev

Escalate-fast hits are counted apart: an escalation cannot be verified by replay. A partial hit = the playbook's patch was kept as a verified improvement but the incident had a second fault (investigated normally).
