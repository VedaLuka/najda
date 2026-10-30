"""Doctors: agents that diagnose and fix a broken patient using only an Environment."""
from hack.doctors import baselines, najda, single_llm  # noqa: F401  (registers doctors)
from hack.doctors.base import DOCTORS, get_doctor  # noqa: F401
