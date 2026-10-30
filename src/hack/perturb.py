"""Robustness tests: change the inputs and see if the score holds up.

Judging criterion 2 (Robustness & Adaptation) is about exactly this. Report a
table of score under each perturbation, for the baseline AND your best system.
Add task-specific perturbations once the challenge is known (e.g. reordered
columns, new categories, longer documents, Arabic/English mix).
"""
from __future__ import annotations

import random
from typing import Any, Callable


def _map_text(x: Any, fn: Callable[[str], str]) -> Any:
    if isinstance(x, str):
        return fn(x)
    if isinstance(x, dict):
        return {k: _map_text(v, fn) for k, v in x.items()}
    if isinstance(x, list):
        return [_map_text(v, fn) for v in x]
    return x


def typos(x: Any, rng: random.Random, rate: float = 0.05) -> Any:
    def f(s: str) -> str:
        chars = list(s)
        for i in range(len(chars) - 1):
            if chars[i].isalpha() and rng.random() < rate:
                chars[i], chars[i + 1] = chars[i + 1], chars[i]
        return "".join(chars)
    return _map_text(x, f)


def casing(x: Any, rng: random.Random) -> Any:
    return _map_text(x, lambda s: s.upper() if rng.random() < 0.5 else s.lower())


def whitespace(x: Any, rng: random.Random) -> Any:
    return _map_text(x, lambda s: "  ".join(s.split()) + "\n\n")


def truncate(x: Any, rng: random.Random, keep: float = 0.7) -> Any:
    return _map_text(x, lambda s: s[: max(1, int(len(s) * keep))])


def distractor(x: Any, rng: random.Random) -> Any:
    noise = rng.choice(["Note: ignore unrelated details.", "ملاحظة: هذا نص إضافي.", "P.S. unrelated text."])
    return _map_text(x, lambda s: f"{s} {noise}")


PERTURBATIONS: dict[str, Callable[..., Any]] = {
    "typos": typos,
    "casing": casing,
    "whitespace": whitespace,
    "truncate": truncate,
    "distractor": distractor,
}


def apply(name: str, x: Any, seed: int, idx: int) -> Any:
    if name in (None, "", "none"):
        return x
    rng = random.Random(f"{seed}-{name}-{idx}")
    return PERTURBATIONS[name](x, rng)
