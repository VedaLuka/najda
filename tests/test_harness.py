"""Fast tests that must always pass. Add one test per bug you fix during the weekend."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hack import metrics as M  # noqa: E402
from hack import perturb  # noqa: E402
from hack.systems import SYSTEMS, get_system  # noqa: E402


def test_metrics_bounds():
    assert M.exact_match("a", "a") == 1.0
    assert M.normalized_match("  Positive ", "positive") == 1.0
    assert M.normalized_match("مُمْتاز", "ممتاز") == 1.0  # diacritics ignored
    assert 0.0 <= M.token_f1("the cat sat", "a cat sat down") <= 1.0
    assert M.macro_f1(["a", "b"], ["a", "b"]) == 1.0


def test_primary_metric_exists():
    assert M.PRIMARY_METRIC in M.EXAMPLE_METRICS or M.PRIMARY_METRIC in M.CORPUS_METRICS


def test_perturbations_deterministic():
    for name in perturb.PERTURBATIONS:
        a = perturb.apply(name, {"text": "hello world"}, seed=1, idx=0)
        b = perturb.apply(name, {"text": "hello world"}, seed=1, idx=0)
        assert a == b, name


def test_baselines_run():
    train = [{"id": "1", "input": "x", "expected": "yes"}, {"id": "2", "input": "y", "expected": "yes"}]
    s = get_system("baseline_majority")
    s.fit(train)
    assert s.predict("anything") == "yes"
    assert "baseline_echo" in SYSTEMS
