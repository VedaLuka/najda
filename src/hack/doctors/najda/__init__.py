"""Najda versions. Each version is a flag set over the same loop so every component can be ablated."""
from __future__ import annotations

from hack.doctors.base import register
from hack.doctors.najda.loop import Najda


@register("najda_v1")
class NajdaV1(Najda):
    """Core loop only: investigate with tools, hypotheses, one patch at a time, verify by replay, rollback."""
    flags = {"diff_diagnosis": False, "guardrails": False, "canary": False, "bisect": False}


@register("najda_v2")
class NajdaV2(Najda):
    """+ differential diagnosis (grounded hypotheses) + guardrails + canary + config bisection."""
    flags = {"diff_diagnosis": True, "guardrails": True, "canary": True, "bisect": True}


@register("najda_v3")
class NajdaV3(Najda):
    """v2 + structured money-at-risk (invariant types + payment ledger; prompt rollback is approval-gated, never
    refused for money) + replay error digest fed into the next investigation round."""
    flags = {**NajdaV2.flags, "structured_money": True, "replay_digest": True}


@register("najda_v4_nt")
class NajdaV4NoTriage(Najda):
    """v3 + playbooks: structured-signature memory of verified fixes, matched before any big-model call and
    applied through the same guardrails and verification. No triage (ablation arm)."""
    flags = {**NajdaV3.flags, "playbooks": True}


@register("najda_v4")
class NajdaV4(Najda):
    """v4_nt + cheap triage call (small model) that writes the big model's evidence brief."""
    flags = {**NajdaV4NoTriage.flags, "triage": True}


# ------------------------- step 5 ablation arms: najda_v4 minus ONE component -------------------------
# Memory stays OFF in the ablation runs so every arm is comparable with the memory-OFF v4 run.
# "minus triage" is `najda_v4_nt` above.

@register("najda_v4_no_diffdiag")
class NajdaV4NoDiffDiag(Najda):
    """v4 without differential diagnosis: hypotheses need no failing-only span evidence."""
    flags = {**NajdaV4.flags, "diff_diagnosis": False}


@register("najda_v4_no_guardrails")
class NajdaV4NoGuardrails(Najda):
    """v4 without guardrails: no blast-radius / protected-knob / money-at-risk checks before a patch."""
    flags = {**NajdaV4.flags, "guardrails": False}


@register("najda_v4_no_canary")
class NajdaV4NoCanary(Najda):
    """v4 without the canary replay: every patch goes straight to the full replay."""
    flags = {**NajdaV4.flags, "canary": False}


@register("najda_v4_no_bisect")
class NajdaV4NoBisect(Najda):
    """v4 without config bisection: the model reads the config history itself."""
    flags = {**NajdaV4.flags, "bisect": False}


@register("najda_v4_no_code_rules")
class NajdaV4NoCodeRules(Najda):
    """v4 without the code rules: no healthy shortcut, no free baseline replay, no transient detection;
    the model is asked on every incident and its 'nothing to fix' is accepted."""
    flags = {**NajdaV4.flags, "code_rules": False}
