import httpx
import pytest
import respx

from sentinel_eval.models import EvalPrediction
from sentinel_eval.online.consistency import (
    UpstashVectorError,
    make_ollama_embed_fn,
    query_upstash_vector,
    score_consistency,
)

OLLAMA_URL = "http://ollama.test:11434"
UPSTASH_URL = "https://upstash.test"


@pytest.fixture(autouse=True)
def _upstash_env(monkeypatch):
    monkeypatch.setenv("UPSTASH_VECTOR_REST_URL", UPSTASH_URL)
    monkeypatch.setenv("UPSTASH_VECTOR_REST_TOKEN", "test-token")
    monkeypatch.setenv("OLLAMA_URL", OLLAMA_URL)


@respx.mock
def test_make_ollama_embed_fn_sends_search_query_prefix():
    route = respx.post(f"{OLLAMA_URL}/api/embeddings").mock(
        return_value=httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})
    )

    embed = make_ollama_embed_fn()
    vector = embed("some narrative text")

    assert vector == [0.1, 0.2, 0.3]
    request_body = route.calls.last.request.content
    assert b"search_query: some narrative text" in request_body


def test_query_upstash_vector_raises_without_credentials(monkeypatch):
    monkeypatch.delenv("UPSTASH_VECTOR_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_VECTOR_REST_TOKEN", raising=False)

    with pytest.raises(UpstashVectorError):
        query_upstash_vector([0.1, 0.2])


@respx.mock
def test_query_upstash_vector_sends_correct_shape_and_filters_by_threshold():
    route = respx.post(f"{UPSTASH_URL}/query/transactions").mock(
        return_value=httpx.Response(
            200,
            json={
                "result": [
                    {"id": "txn_a", "score": 0.97, "metadata": {"analysis": {"risk_level": "high"}}},
                    {"id": "txn_b", "score": 0.5, "metadata": {"analysis": {"risk_level": "low"}}},
                ]
            },
        )
    )

    matches = query_upstash_vector([0.1, 0.2], threshold=0.9)

    assert len(matches) == 1
    assert matches[0].id == "txn_a"
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer test-token"


@respx.mock
def test_score_consistency_no_neighbors_is_consistent_by_default():
    respx.post(f"{UPSTASH_URL}/query/transactions").mock(
        return_value=httpx.Response(200, json={"result": []})
    )

    prediction = EvalPrediction(id="txn-1", raw_output={}, label="high", confidence=0.8)
    result = score_consistency(prediction, "narrative text", embed_fn=lambda t: [0.1])

    assert result.consistent is True
    assert result.neighbor_labels == []


@respx.mock
def test_score_consistency_agrees_with_majority_neighbor_label():
    respx.post(f"{UPSTASH_URL}/query/transactions").mock(
        return_value=httpx.Response(
            200,
            json={
                "result": [
                    {"id": "a", "score": 0.97, "metadata": {"analysis": {"risk_level": "high"}}},
                    {"id": "b", "score": 0.96, "metadata": {"analysis": {"risk_level": "high"}}},
                    {"id": "c", "score": 0.95, "metadata": {"analysis": {"risk_level": "low"}}},
                ]
            },
        )
    )

    prediction = EvalPrediction(id="txn-2", raw_output={}, label="high", confidence=0.8)
    result = score_consistency(prediction, "narrative text", embed_fn=lambda t: [0.1])

    assert result.consistent is True
    assert result.neighbor_labels == ["high", "high", "low"]


@respx.mock
def test_score_consistency_flags_divergence_from_majority_neighbor_label():
    respx.post(f"{UPSTASH_URL}/query/transactions").mock(
        return_value=httpx.Response(
            200,
            json={
                "result": [
                    {"id": "a", "score": 0.97, "metadata": {"analysis": {"risk_level": "low"}}},
                    {"id": "b", "score": 0.96, "metadata": {"analysis": {"risk_level": "low"}}},
                ]
            },
        )
    )

    prediction = EvalPrediction(id="txn-3", raw_output={}, label="critical", confidence=0.9)
    result = score_consistency(prediction, "narrative text", embed_fn=lambda t: [0.1])

    assert result.consistent is False


@respx.mock
def test_score_consistency_skips_neighbors_missing_risk_level_metadata():
    respx.post(f"{UPSTASH_URL}/query/transactions").mock(
        return_value=httpx.Response(
            200,
            json={
                "result": [
                    {"id": "a", "score": 0.97, "metadata": {}},
                    {"id": "b", "score": 0.96, "metadata": {"analysis": {"risk_level": "low"}}},
                ]
            },
        )
    )

    prediction = EvalPrediction(id="txn-4", raw_output={}, label="low", confidence=0.9)
    result = score_consistency(prediction, "narrative text", embed_fn=lambda t: [0.1])

    assert result.neighbor_labels == ["low"]
    assert result.consistent is True
