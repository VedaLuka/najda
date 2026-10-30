"""Every version of the solution is a named 'system' in this registry.

Rules:
- Never edit an old system to make it better. Copy it, give it a new name, register it.
  That way every row in the experiment log can be re-run and compared later.
- Each system takes a config dict, so one class can cover several ablations
  (e.g. use_retrieval=True/False) without new code.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Callable

SYSTEMS: dict[str, type["System"]] = {}


def register(name: str) -> Callable[[type["System"]], type["System"]]:
    def wrap(cls: type["System"]) -> type["System"]:
        if name in SYSTEMS:
            raise ValueError(f"System '{name}' already registered")
        cls.name = name
        SYSTEMS[name] = cls
        return cls
    return wrap


class System:
    name = "base"

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    def fit(self, train: list[dict]) -> None:
        """Optional: learn from training examples (majority label, few-shot pool, index...)."""

    def predict(self, x: Any) -> Any:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Baselines. Build these FIRST on Friday, before anything clever.
# Judges reward "approaches that beat simpler baselines" - you need the baseline number.
# ---------------------------------------------------------------------------

@register("baseline_majority")
class MajorityBaseline(System):
    """Always predicts the most common expected output in train. Floor for classification tasks."""

    def fit(self, train: list[dict]) -> None:
        counts = Counter(str(ex["expected"]) for ex in train)
        self.answer = counts.most_common(1)[0][0] if counts else ""

    def predict(self, x: Any) -> Any:
        return self.answer


@register("baseline_echo")
class EchoBaseline(System):
    """Returns the input unchanged. Floor for transformation / extraction tasks."""

    def predict(self, x: Any) -> Any:
        return x


@register("llm_zero_shot")
class LLMZeroShot(System):
    """Simplest LLM system: one prompt, no examples. Usually your second baseline."""

    def predict(self, x: Any) -> Any:
        from hack.llm import call_llm

        prompt = self.config.get("prompt", "Answer the task.\n\nInput:\n{input}\n\nAnswer:")
        return call_llm(
            prompt.format(input=x),
            model=self.config.get("model"),
            temperature=self.config.get("temperature", 0.0),
        ).strip()


def get_system(name: str, config: dict[str, Any] | None = None) -> System:
    if name not in SYSTEMS:
        raise KeyError(f"Unknown system '{name}'. Known: {sorted(SYSTEMS)}")
    return SYSTEMS[name](config)
