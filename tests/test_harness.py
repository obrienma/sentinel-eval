import json
from pathlib import Path

import pytest

from sentinel_eval.harness import run_eval
from sentinel_eval.models import EvalDataset, EvalPrediction

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "compliance_dataset.json"


def load_dataset() -> EvalDataset:
    data = json.loads(FIXTURE_PATH.read_text())
    return EvalDataset.model_validate(data)


def _rule_based_label(input_data: dict) -> str:
    """Mirrors the exact rule the fixture's expected_label values were generated from:
    null status -> unknown, otherwise bucket anomaly_score at 0.1 / 0.5 / 0.85.
    """
    if input_data.get("status") is None:
        return "unknown"
    score = input_data["anomaly_score"]
    if score < 0.1:
        return "low"
    if score < 0.5:
        return "medium"
    if score < 0.85:
        return "high"
    return "critical"


def perfect_sut(input_data: dict) -> EvalPrediction:
    return EvalPrediction(
        id=input_data["source_id"],
        raw_output=input_data,
        label=_rule_based_label(input_data),
        confidence=0.9,
    )


def test_run_eval_perfect_predictor_scores_1_0():
    dataset = load_dataset()
    report = run_eval(perfect_sut, dataset)

    assert report.total == len(dataset)
    assert report.correct == len(dataset)
    assert report.accuracy == pytest.approx(1.0)
    assert len(report.predictions) == len(dataset)

    for metrics in report.per_label:
        assert metrics.precision == pytest.approx(1.0)
        assert metrics.recall == pytest.approx(1.0)
        assert metrics.f1 == pytest.approx(1.0)

    label_counts: dict[str, int] = {}
    for example in dataset.examples:
        label_counts[example.expected_label] = (
            label_counts.get(example.expected_label, 0) + 1
        )
    for metrics in report.per_label:
        assert metrics.support == label_counts[metrics.label]


def test_run_eval_imperfect_predictor_computes_correct_precision_recall():
    dataset = load_dataset()

    def flawed_sut(input_data: dict) -> EvalPrediction:
        label = _rule_based_label(input_data)
        # Deliberately mislabel every "critical" case as "high" to exercise
        # non-trivial precision/recall math.
        if label == "critical":
            label = "high"
        return EvalPrediction(
            id=input_data["source_id"],
            raw_output=input_data,
            label=label,
            confidence=0.7,
        )

    report = run_eval(flawed_sut, dataset)

    expected_labels = [e.expected_label for e in dataset.examples]
    n_critical = expected_labels.count("critical")
    n_high = expected_labels.count("high")
    n_total = len(expected_labels)

    assert report.correct == n_total - n_critical
    assert report.accuracy == pytest.approx((n_total - n_critical) / n_total)

    metrics_by_label = {m.label: m for m in report.per_label}

    # critical is never predicted anymore: no true positives, no false positives.
    critical_metrics = metrics_by_label["critical"]
    assert critical_metrics.support == n_critical
    assert critical_metrics.recall == pytest.approx(0.0)
    assert critical_metrics.precision == pytest.approx(0.0)
    assert critical_metrics.f1 == pytest.approx(0.0)

    # high absorbs every mislabeled critical as a false positive, but still
    # correctly recalls every genuine "high" example.
    high_metrics = metrics_by_label["high"]
    assert high_metrics.recall == pytest.approx(1.0)
    assert high_metrics.precision == pytest.approx(n_high / (n_high + n_critical))

    # labels untouched by the flaw stay perfect.
    for label in ("low", "medium", "unknown"):
        metrics = metrics_by_label[label]
        assert metrics.precision == pytest.approx(1.0)
        assert metrics.recall == pytest.approx(1.0)
        assert metrics.f1 == pytest.approx(1.0)
