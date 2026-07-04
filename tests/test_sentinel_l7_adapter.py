import json

import httpx
import pytest
import respx

from sentinel_eval.adapters.sentinel_l7 import SentinelL7Error, make_sentinel_l7_system_under_test

MCP_URL = "http://sentinel.test/mcp"


def _mcp_result(summary: dict, *, is_error: bool = False) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [{"type": "text", "text": json.dumps(summary)}],
            "isError": is_error,
        },
    }


@respx.mock
def test_successful_call_maps_risk_level_to_label():
    respx.post(MCP_URL).mock(
        return_value=httpx.Response(
            200,
            json=_mcp_result(
                {
                    "source": "cache_miss",
                    "is_threat": True,
                    "message": "High value at ACME Corp",
                    "elapsed_ms": 42.1,
                    "risk_level": "high",
                    "narrative": "High value at ACME Corp",
                    "confidence": 0.87,
                    "policy_refs": ["AML-3.2"],
                }
            ),
        )
    )

    sut = make_sentinel_l7_system_under_test(mcp_url=MCP_URL)
    prediction = sut({"id": "txn-1", "amount": 500.0, "currency": "USD", "merchant": "ACME Corp"})

    assert prediction.id == "txn-1"
    assert prediction.label == "high"
    assert prediction.confidence == 0.87
    assert prediction.raw_output["policy_refs"] == ["AML-3.2"]
    assert prediction.metadata == {"source": "cache_miss", "elapsed_ms": 42.1}


@respx.mock
def test_null_confidence_maps_to_zero_on_fallback_path():
    respx.post(MCP_URL).mock(
        return_value=httpx.Response(
            200,
            json=_mcp_result(
                {
                    "source": "fallback",
                    "is_threat": False,
                    "message": "Layer 7 Clear",
                    "elapsed_ms": 3.0,
                    "risk_level": "low",
                    "narrative": "Layer 7 Clear",
                    "confidence": None,
                    "policy_refs": [],
                }
            ),
        )
    )

    sut = make_sentinel_l7_system_under_test(mcp_url=MCP_URL)
    prediction = sut({"id": "txn-2", "amount": 10.0, "currency": "USD", "merchant": "Cafe"})

    assert prediction.confidence == 0.0


@respx.mock
def test_missing_id_generates_a_correlation_uuid():
    respx.post(MCP_URL).mock(
        return_value=httpx.Response(
            200,
            json=_mcp_result(
                {
                    "source": "cache_hit",
                    "is_threat": False,
                    "message": "ok",
                    "elapsed_ms": 1.0,
                    "risk_level": "low",
                    "narrative": "ok",
                    "confidence": None,
                    "policy_refs": [],
                }
            ),
        )
    )

    sut = make_sentinel_l7_system_under_test(mcp_url=MCP_URL)
    prediction = sut({"amount": 10.0, "currency": "USD", "merchant": "Cafe"})

    assert prediction.id  # a UUID string, non-empty
    assert len(prediction.id) == 36


@respx.mock
def test_json_rpc_error_envelope_raises():
    respx.post(MCP_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32602, "message": "Missing [name] parameter."},
            },
        )
    )

    sut = make_sentinel_l7_system_under_test(mcp_url=MCP_URL)

    with pytest.raises(SentinelL7Error):
        sut({"id": "txn-3", "amount": 10.0, "currency": "USD", "merchant": "Cafe"})


@respx.mock
def test_tool_level_is_error_raises():
    respx.post(MCP_URL).mock(
        return_value=httpx.Response(
            200,
            json=_mcp_result({"error": "The amount field is required."}, is_error=True),
        )
    )

    sut = make_sentinel_l7_system_under_test(mcp_url=MCP_URL)

    with pytest.raises(SentinelL7Error):
        sut({"id": "txn-4", "currency": "USD", "merchant": "Cafe"})


@respx.mock
def test_non_2xx_http_status_raises():
    respx.post(MCP_URL).mock(return_value=httpx.Response(500, text="internal error"))

    sut = make_sentinel_l7_system_under_test(mcp_url=MCP_URL)

    with pytest.raises(SentinelL7Error):
        sut({"id": "txn-5", "amount": 10.0, "currency": "USD", "merchant": "Cafe"})


@respx.mock
def test_driver_override_is_sent_as_a_tool_argument():
    route = respx.post(MCP_URL).mock(
        return_value=httpx.Response(
            200,
            json=_mcp_result(
                {
                    "source": "driver_override",
                    "is_threat": True,
                    "message": "High value at ACME Corp",
                    "elapsed_ms": 55.0,
                    "risk_level": "high",
                    "narrative": "High value at ACME Corp",
                    "confidence": 0.8,
                    "policy_refs": [],
                }
            ),
        )
    )

    sut = make_sentinel_l7_system_under_test(mcp_url=MCP_URL, driver="openrouter")
    prediction = sut({"id": "txn-7", "amount": 500.0, "currency": "USD", "merchant": "ACME Corp"})

    assert prediction.metadata["source"] == "driver_override"
    sent_body = json.loads(route.calls.last.request.content)
    assert sent_body["params"]["arguments"]["driver"] == "openrouter"


@respx.mock
def test_no_driver_argument_sent_when_driver_not_set():
    route = respx.post(MCP_URL).mock(
        return_value=httpx.Response(
            200,
            json=_mcp_result(
                {
                    "source": "cache_miss",
                    "is_threat": False,
                    "message": "ok",
                    "elapsed_ms": 1.0,
                    "risk_level": "low",
                    "narrative": "ok",
                    "confidence": None,
                    "policy_refs": [],
                }
            ),
        )
    )

    sut = make_sentinel_l7_system_under_test(mcp_url=MCP_URL)
    sut({"id": "txn-8", "amount": 10.0, "currency": "USD", "merchant": "Cafe"})

    sent_body = json.loads(route.calls.last.request.content)
    assert "driver" not in sent_body["params"]["arguments"]


@respx.mock
def test_default_mcp_url_matches_config():
    from sentinel_eval import config

    route = respx.post(config.sentinel_l7_mcp_url()).mock(
        return_value=httpx.Response(
            200,
            json=_mcp_result(
                {
                    "source": "cache_hit",
                    "is_threat": False,
                    "message": "ok",
                    "elapsed_ms": 1.0,
                    "risk_level": "low",
                    "narrative": "ok",
                    "confidence": None,
                    "policy_refs": [],
                }
            ),
        )
    )

    sut = make_sentinel_l7_system_under_test()
    sut({"id": "txn-6", "amount": 10.0, "currency": "USD", "merchant": "Cafe"})

    assert route.called
