import httpx
import respx
from opentelemetry import trace
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from arbiter_l8.models import EvalPrediction
from arbiter_l8.online import judge as judge_module
from arbiter_l8.online.judge import JudgeCircuitBreaker
from arbiter_l8.online.pipeline import evaluate_item

UPSTASH_URL = "https://upstash-pipeline.test"


def _capture_spans():
    exporter = InMemorySpanExporter()
    trace.get_tracer_provider().add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


def _flagged_prediction() -> EvalPrediction:
    # Low confidence trips check_confidence_threshold -> flagged, same as
    # the judge-escalation test below.
    return EvalPrediction(
        id="txn-3",
        raw_output={"status": "degraded"},
        label="high",
        confidence=0.1,
    )


def test_evaluate_item_only_runs_heuristics_when_not_flagged():
    exporter = _capture_spans()

    prediction = EvalPrediction(
        id="txn-1",
        raw_output={"status": "nominal"},
        label="low",
        confidence=0.95,
    )

    result = evaluate_item(prediction)

    assert result.heuristic_result.flagged is False
    assert result.disagreement_result is None
    assert result.consistency_result is None
    assert result.judge_verdict is None

    span_names = {s.name for s in exporter.get_finished_spans()}
    assert span_names == {"heuristics_check", "evaluate_item"}


def test_evaluate_item_escalates_to_judge_when_flagged_and_judge_supplied(monkeypatch):
    exporter = _capture_spans()

    monkeypatch.setattr(judge_module, "_call_ollama", lambda p, c: "high")

    # Low confidence trips check_confidence_threshold -> flagged.
    prediction = EvalPrediction(
        id="txn-2",
        raw_output={"status": "degraded"},
        label="high",
        confidence=0.1,
    )

    result = evaluate_item(prediction, judge=JudgeCircuitBreaker())

    assert result.heuristic_result.flagged is True
    assert result.judge_verdict is not None
    assert result.judge_verdict.verdict_label == "high"
    # Neither dependency was supplied, so these layers are skipped entirely.
    assert result.disagreement_result is None
    assert result.consistency_result is None

    span_names = {s.name for s in exporter.get_finished_spans()}
    assert span_names == {"heuristics_check", "ollama_attempt", "judge_call", "evaluate_item"}
    assert "cross_provider_disagreement" not in span_names
    assert "embedding_consistency" not in span_names


def test_evaluate_item_escalates_to_disagreement_when_flagged_and_providers_supplied():
    exporter = _capture_spans()

    def gemini(input_data):
        return EvalPrediction(id="p", raw_output=input_data, label="high", confidence=0.9)

    def openrouter(input_data):
        return EvalPrediction(id="p", raw_output=input_data, label="low", confidence=0.8)

    result = evaluate_item(
        _flagged_prediction(),
        providers={"gemini": gemini, "openrouter": openrouter},
    )

    assert result.heuristic_result.flagged is True
    assert result.disagreement_result is not None
    assert result.disagreement_result.agreed is False
    # Neither of the other two optional layers was wired up.
    assert result.consistency_result is None
    assert result.judge_verdict is None

    span_names = {s.name for s in exporter.get_finished_spans()}
    assert span_names == {"heuristics_check", "cross_provider_disagreement", "evaluate_item"}


@respx.mock
def test_evaluate_item_escalates_to_consistency_when_flagged_and_embed_fn_supplied(monkeypatch):
    monkeypatch.setenv("UPSTASH_VECTOR_REST_URL", UPSTASH_URL)
    monkeypatch.setenv("UPSTASH_VECTOR_REST_TOKEN", "test-token")
    respx.post(f"{UPSTASH_URL}/query/transactions").mock(
        return_value=httpx.Response(200, json={"result": []})
    )
    exporter = _capture_spans()

    result = evaluate_item(
        _flagged_prediction(),
        embed_fn=lambda text: [0.1, 0.2],
        consistency_text="narrative text",
    )

    assert result.heuristic_result.flagged is True
    assert result.consistency_result is not None
    assert result.consistency_result.consistent is True
    # Neither of the other two optional layers was wired up.
    assert result.disagreement_result is None
    assert result.judge_verdict is None

    span_names = {s.name for s in exporter.get_finished_spans()}
    assert span_names == {"heuristics_check", "embedding_consistency", "evaluate_item"}


@respx.mock
def test_evaluate_item_runs_all_four_layers_when_flagged_and_everything_supplied(monkeypatch):
    monkeypatch.setenv("UPSTASH_VECTOR_REST_URL", UPSTASH_URL)
    monkeypatch.setenv("UPSTASH_VECTOR_REST_TOKEN", "test-token")
    respx.post(f"{UPSTASH_URL}/query/transactions").mock(
        return_value=httpx.Response(200, json={"result": []})
    )
    monkeypatch.setattr(judge_module, "_call_ollama", lambda p, c: "high")
    exporter = _capture_spans()

    def gemini(input_data):
        return EvalPrediction(id="p", raw_output=input_data, label="high", confidence=0.9)

    result = evaluate_item(
        _flagged_prediction(),
        providers={"gemini": gemini},
        embed_fn=lambda text: [0.1, 0.2],
        consistency_text="narrative text",
        judge=JudgeCircuitBreaker(),
    )

    assert result.heuristic_result.flagged is True
    assert result.disagreement_result is not None
    assert result.consistency_result is not None
    assert result.judge_verdict is not None
    assert result.judge_verdict.verdict_label == "high"

    span_names = {s.name for s in exporter.get_finished_spans()}
    assert span_names == {
        "heuristics_check",
        "cross_provider_disagreement",
        "embedding_consistency",
        "ollama_attempt",
        "judge_call",
        "evaluate_item",
    }
