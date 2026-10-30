"""Hajz (حجز): a restaurant reservation bot, the UNSEEN second patient for the transfer split.

Same observability shape as the order bot (JSONL spans -> OTel), its own tools (check_availability,
create_booking, charge_deposit, send_confirmation), control panel, knob docs, invariants and faults.
Shared infrastructure (clock, chaos layer, tracer, control panel, OTel adapter) is imported from hack.patient.
"""
