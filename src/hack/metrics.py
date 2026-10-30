"""Metrics. Replace or add the official metric as soon as the challenge is revealed.

Each metric takes (prediction, expected) for ONE example and returns a float in [0, 1].
The harness averages them. If the official metric is corpus-level (e.g. F1 over
all examples), add it to CORPUS_METRICS instead.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Callable


def _norm(s: Any) -> str:
    s = unicodedata.normalize("NFKC", str(s)).lower().strip()
    s = re.sub(r"[ً-ْ]", "", s)  # strip Arabic diacritics
    s = re.sub(r"\s+", " ", s)
    return s


def exact_match(pred: Any, expected: Any) -> float:
    return float(str(pred).strip() == str(expected).strip())


def normalized_match(pred: Any, expected: Any) -> float:
    return float(_norm(pred) == _norm(expected))


def token_f1(pred: Any, expected: Any) -> float:
    p, e = _norm(pred).split(), _norm(expected).split()
    if not p and not e:
        return 1.0
    common = sum(min(p.count(t), e.count(t)) for t in set(p))
    if common == 0:
        return 0.0
    precision, recall = common / len(p), common / len(e)
    return 2 * precision * recall / (precision + recall)


EXAMPLE_METRICS: dict[str, Callable[[Any, Any], float]] = {
    "exact_match": exact_match,
    "normalized_match": normalized_match,
    "token_f1": token_f1,
}


def macro_f1(preds: list[Any], expected: list[Any]) -> float:
    labels = sorted({str(x) for x in expected} | {str(x) for x in preds})
    f1s = []
    for lab in labels:
        tp = sum(1 for p, e in zip(preds, expected) if str(p) == lab and str(e) == lab)
        fp = sum(1 for p, e in zip(preds, expected) if str(p) == lab and str(e) != lab)
        fn = sum(1 for p, e in zip(preds, expected) if str(p) != lab and str(e) == lab)
        denom = 2 * tp + fp + fn
        f1s.append(2 * tp / denom if denom else 0.0)
    return sum(f1s) / len(f1s) if f1s else 0.0


CORPUS_METRICS: dict[str, Callable[[list[Any], list[Any]], float]] = {
    "macro_f1": macro_f1,
}

# The ONE number you optimise and report. Change when the official metric is known.
PRIMARY_METRIC = "normalized_match"
