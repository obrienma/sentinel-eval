"""System-under-test adapter for Sentinel-L7's compliance analysis.

Sentinel-L7 exposes no plain HTTP controller for ComplianceDriver::analyze()
— the only external surface is an MCP server (routes/ai.php:
Mcp::web('/mcp', SentinelServer::class)), tool name `analyze-transaction`
(Str::kebab(class_basename(AnalyzeTransaction::class)) — note this is
kebab-case; the server's own human-readable instructions text says
"analyze_transaction", which is prose for an LLM reader, not the actual
JSON-RPC tool identifier). This is a hand-rolled minimal MCP-over-HTTP
client for that one tool call — not the full `mcp` SDK — matching
docs/adr/0001-standalone-module.md's spirit of thin, service-specific
adapters living outside the harness core.

Verified against vendor/laravel/mcp source (not assumed): Server::handle()
dispatches directly to whatever `method` is sent with no requirement that
an `initialize` handshake happened first, so a single-shot `tools/call`
request works standalone — no session bookkeeping needed.

The tool's result content is Response::json($result), i.e.
`result.content[0].text` is itself a JSON-encoded string (double-decode
required), decoding to TransactionProcessorService::process()'s summary
array: `{source, is_threat, message, elapsed_ms, risk_level, narrative,
confidence, policy_refs}`. `risk_level`/`narrative`/`confidence`/
`policy_refs` were added to that summary (previously it only exposed a
collapsed boolean `is_threat`) specifically so this adapter could score
against Sentinel-L7's real risk_level taxonomy instead of a boolean.
"""

from __future__ import annotations

import itertools
import json
import uuid
from typing import Any

import httpx

from sentinel_eval import config
from sentinel_eval.harness import SystemUnderTest
from sentinel_eval.models import EvalPrediction

_TOOL_NAME = "analyze-transaction"
_request_id_counter = itertools.count(1)


class SentinelL7Error(RuntimeError):
    """Raised on a JSON-RPC error, an MCP tool-level error (isError), or a
    non-2xx HTTP response from Sentinel-L7's /mcp endpoint.
    """

    def __init__(self, message: str, *, detail: Any = None):
        self.detail = detail
        super().__init__(message)


def make_sentinel_l7_system_under_test(
    *,
    mcp_url: str | None = None,
    client: httpx.Client | None = None,
    timeout: float = 10.0,
    driver: str | None = None,
) -> SystemUnderTest:
    """Build a system_under_test callable that scores input through Sentinel-L7.

    Each `input` dict must be shaped like the analyze-transaction tool's
    arguments: `{"amount": float, "currency": str, "merchant": str,
    "type"?: str, "category"?: str, "id"?: str}`. If `id` is omitted, a
    fresh UUID is generated for correlation — Sentinel-L7's response
    doesn't echo the id back, so it's carried client-side, not round-tripped.

    Maps `risk_level` -> `label`, `confidence` -> `confidence` (0.0 when
    Sentinel-L7 returns null, i.e. the rule-based fallback path ran with no
    AI model involved — EvalPrediction.confidence is non-optional, and 0.0
    is the lowest-confidence signal available, not a guess at a real score).

    `driver` forces a specific ComplianceManager driver ('gemini' /
    'openrouter' / 'ollama') via the tool's optional `driver` argument
    (Sentinel-L7 Phase 3 step 6) instead of the app-wide configured
    default. Building one system_under_test per driver is how
    online.disagreement.score_disagreement gets independent per-provider
    verdicts for the same transaction — each override call bypasses
    Sentinel-L7's semantic vector cache entirely, so results are never a
    stale cached verdict from a different provider.
    """
    resolved_url = mcp_url or config.sentinel_l7_mcp_url()
    http_client = client or httpx.Client(timeout=timeout)

    def system_under_test(input_data: dict) -> EvalPrediction:
        correlation_id = input_data.get("id") or str(uuid.uuid4())
        arguments = {**input_data, "id": correlation_id}
        if driver is not None:
            arguments["driver"] = driver

        response = http_client.post(
            resolved_url,
            json={
                "jsonrpc": "2.0",
                "id": next(_request_id_counter),
                "method": "tools/call",
                "params": {"name": _TOOL_NAME, "arguments": arguments},
            },
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        if response.status_code >= 400:
            raise SentinelL7Error(
                f"Sentinel-L7 /mcp call failed ({response.status_code})", detail=response.text
            )

        envelope = response.json()
        if "error" in envelope:
            raise SentinelL7Error("Sentinel-L7 MCP error response", detail=envelope["error"])

        result = envelope["result"]
        content_text = result["content"][0]["text"]
        summary = json.loads(content_text)

        if result.get("isError"):
            raise SentinelL7Error("Sentinel-L7 tool call returned isError", detail=summary)

        return EvalPrediction(
            id=correlation_id,
            raw_output=summary,
            label=summary["risk_level"],
            confidence=summary["confidence"] if summary["confidence"] is not None else 0.0,
            metadata={"source": summary["source"], "elapsed_ms": summary["elapsed_ms"]},
        )

    return system_under_test
