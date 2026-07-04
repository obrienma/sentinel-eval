import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from sentinel_eval.models import EvalPrediction
from sentinel_eval.online.disagreement import score_disagreement


def _capture_spans():
    exporter = InMemorySpanExporter()
    trace.get_tracer_provider().add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


def _prediction(label: str, confidence: float) -> EvalPrediction:
    return EvalPrediction(id="txn-1", raw_output={}, label=label, confidence=confidence)


def test_agreeing_providers_report_agreed_true_and_confidence_spread():
    exporter = _capture_spans()

    providers = {
        "gemini": lambda d: _prediction("high", 0.8),
        "openrouter": lambda d: _prediction("high", 0.6),
    }

    result = score_disagreement({"id": "txn-1", "amount": 9000}, providers)

    assert result.prediction_id == "txn-1"
    assert result.labels_by_provider == {"gemini": "high", "openrouter": "high"}
    assert result.confidence_by_provider == {"gemini": 0.8, "openrouter": 0.6}
    assert result.errors_by_provider == {}
    assert result.agreed is True
    assert result.confidence_spread == pytest.approx(0.2)

    span_names = [s.name for s in exporter.get_finished_spans()]
    assert span_names == ["cross_provider_disagreement"]


def test_disagreeing_providers_report_agreed_false():
    providers = {
        "gemini": lambda d: _prediction("medium", 0.7),
        "openrouter": lambda d: _prediction("high", 0.9),
    }

    result = score_disagreement({"id": "txn-2"}, providers)

    assert result.agreed is False
    assert result.labels_by_provider == {"gemini": "medium", "openrouter": "high"}


def test_a_provider_error_is_surfaced_not_swallowed_and_forces_disagreement():
    def openrouter_fails(d):
        raise RuntimeError("OpenRouter unavailable")

    providers = {
        "gemini": lambda d: _prediction("high", 0.8),
        "openrouter": openrouter_fails,
    }

    result = score_disagreement({"id": "txn-3"}, providers)

    assert result.agreed is False
    assert result.labels_by_provider == {"gemini": "high"}
    assert result.errors_by_provider == {"openrouter": "OpenRouter unavailable"}
    # Only one successful provider — no meaningful spread to report.
    assert result.confidence_spread == 0.0


def test_all_providers_erroring_produces_no_labels_and_agreed_false():
    def always_fails(d):
        raise RuntimeError("down")

    providers = {"gemini": always_fails, "openrouter": always_fails}

    result = score_disagreement({"id": "txn-4"}, providers)

    assert result.agreed is False
    assert result.labels_by_provider == {}
    assert set(result.errors_by_provider.keys()) == {"gemini", "openrouter"}


def test_missing_id_generates_a_correlation_uuid():
    providers = {"gemini": lambda d: _prediction("low", 0.9)}

    result = score_disagreement({"amount": 10.0}, providers)

    assert result.prediction_id
    assert len(result.prediction_id) == 36
