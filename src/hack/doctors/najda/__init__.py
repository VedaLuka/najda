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
