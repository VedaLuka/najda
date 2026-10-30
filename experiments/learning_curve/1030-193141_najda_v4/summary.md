# Learning curve: `najda_v4` on dev (memory OFF vs ON)

| arm | seeds | accuracy [95% CI] | $/incident [95% CI] | $/stream | LLM calls/stream | $ first half | $ second half | hits | esc-fast hits | false matches | hit rate | false-match rate | zero-LLM incidents |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| off | 1 | 0.976 [0.929, 1.000] | 0.0253 [0.0220, 0.0288] | 1.064 | 118.0 | 0.0222 | 0.0285 | 0 | 0 | 0 | 0.00 | 0.00 | 2 |
| on | 3 | 0.929 [0.849, 0.984] | 0.0164 [0.0119, 0.0214] | 0.687 | 72.3 | 0.0154 | 0.0174 | 50 | 3 | 9 | 0.40 | 0.15 | 56 |

Runs: off=1030-193141_najda_v4_dev, on_seed1=1030-193142_najda_v4_dev, on_seed2=1030-193235_najda_v4_dev, on_seed3=1030-193302_najda_v4_dev

Escalate-fast hits are counted apart: an escalation cannot be verified by replay.
