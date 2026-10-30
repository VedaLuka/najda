# Learning curve: `najda_v4_nt` on dev (memory OFF vs ON)

| arm | seeds | accuracy [95% CI] | $/incident [95% CI] | $/stream | LLM calls/stream | $ first half | $ second half | hits | esc-fast hits | false matches | hit rate | false-match rate | zero-LLM incidents |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| off | 1 | 0.976 [0.929, 1.000] | 0.0325 [0.0261, 0.0399] | 1.365 | 79.0 | 0.0260 | 0.0390 | 0 | 0 | 0 | 0.00 | 0.00 | 2 |
| on | 3 | 0.936 [0.873, 0.984] | 0.0212 [0.0139, 0.0294] | 0.892 | 51.0 | 0.0186 | 0.0239 | 50 | 3 | 8 | 0.40 | 0.14 | 56 |

Runs: off=1030-193110_najda_v4_nt_dev, on_seed1=1030-193111_najda_v4_nt_dev, on_seed2=1030-193144_najda_v4_nt_dev, on_seed3=1030-193203_najda_v4_nt_dev

Escalate-fast hits are counted apart: an escalation cannot be verified by replay.
