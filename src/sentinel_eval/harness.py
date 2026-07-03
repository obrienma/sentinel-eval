"""Offline evaluation harness — ground truth, no LLM dependency.

Runs a labeled EvalDataset through a system-under-test callable and scores
its EvalPrediction.label against each example's expected_label. See
docs/adr/0001-standalone-module.md for why this path is fully decoupled
from LLM/judge availability.
"""

from __future__ import annotations

from collections.abc import Callable

from sentinel_eval.models import EvalDataset, EvalPrediction, EvalReport, LabelMetrics

SystemUnderTest = Callable[[dict], EvalPrediction]


def run_eval(system_under_test: SystemUnderTest, dataset: EvalDataset) -> EvalReport:
    """Run `system_under_test` over every example in `dataset` and score it.

    Precision/recall/F1 are computed per label (one-vs-rest) plus an overall
    accuracy. This is a pure ground-truth comparison — no judge, no
    heuristics, no external calls.
    """
    predictions: list[EvalPrediction] = []
    expected_labels: list[str] = []

    for example in dataset.examples:
        prediction = system_under_test(example.input)
        predictions.append(prediction)
        expected_labels.append(example.expected_label)

    predicted_labels = [p.label for p in predictions]
    all_labels = sorted(set(expected_labels) | set(predicted_labels))

    per_label: list[LabelMetrics] = []
    for label in all_labels:
        tp = sum(
            1
            for pred, exp in zip(predicted_labels, expected_labels)
            if pred == label and exp == label
        )
        fp = sum(
            1
            for pred, exp in zip(predicted_labels, expected_labels)
            if pred == label and exp != label
        )
        fn = sum(
            1
            for pred, exp in zip(predicted_labels, expected_labels)
            if pred != label and exp == label
        )
        support = sum(1 for exp in expected_labels if exp == label)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )

        per_label.append(
            LabelMetrics(
                label=label,
                precision=precision,
                recall=recall,
                f1=f1,
                support=support,
            )
        )

    correct = sum(
        1 for pred, exp in zip(predicted_labels, expected_labels) if pred == exp
    )
    total = len(expected_labels)
    accuracy = correct / total if total > 0 else 0.0

    return EvalReport(
        total=total,
        correct=correct,
        accuracy=accuracy,
        per_label=per_label,
        predictions=predictions,
    )
