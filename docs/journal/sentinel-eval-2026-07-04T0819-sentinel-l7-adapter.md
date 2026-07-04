---
id: sentinel-eval-2026-07-04T0819-sentinel-l7-adapter
repo: sentinel-eval
title: "Sentinel-L7 MCP Adapter, and Widening TransactionProcessorService's Grading Output"
date: 2026-07-04
phase: 3
tags: [adapter-pattern, mcp-jsonrpc, additive-change, backward-compatibility]
files: [src/sentinel_eval/adapters/sentinel_l7.py, tests/test_sentinel_l7_adapter.py, README.md]
cross_ref: observability
cross_ref_id: sentinel-eval-2026-07-04T0819-sentinel-l7-adapter
---

Second real system-under-test wrapper. Unlike Synapse-L4, Sentinel-L7
exposes no plain HTTP route for compliance analysis — only an MCP server
(`Mcp::web('/mcp', SentinelServer::class)`). Building this adapter required
first reading `vendor/laravel/mcp` source directly to confirm the wire
protocol (tool name is kebab-case via `Str::kebab(class_basename(...))`,
not the snake_case the server's human-readable instructions text uses;
`tools/call` requires no prior `initialize` handshake in this
implementation — `Server::handle()` dispatches directly to whichever
method arrives; `Response::json($result)` double-encodes, so
`result.content[0].text` must be `json.loads()`-ed again to reach the real
payload) — not assumed from the MCP spec in general, since Laravel's
specific implementation choices (stateless dispatch, no session
enforcement) aren't guaranteed by the spec itself.

### Decision: Widen TransactionProcessorService::process() instead of scoring a bare boolean

Investigation surfaced a real design problem before any adapter code was
written: `AnalyzeTransaction`'s only output was `{source, is_threat,
message, elapsed_ms}` — `TransactionProcessorService::process()` calls
`ComplianceDriver::analyzeTransaction()` internally but discarded
`risk_level`/`narrative`/`confidence`/`policy_refs` after using
`risk_level` transiently to compute the boolean. Presented this fork
directly rather than silently picking a side: score against the boolean
as-is (zero cross-repo risk, but a permanent ceiling on what this eval
framework could ever measure about Sentinel-L7), or widen the real
service's output to expose what it already computes internally. Directed
to widen it — "that MCP was written hastily."

### Decision: Additive-only change, verified against the full existing test suite

Extended `summary()` to add `risk_level`/`narrative`/`confidence`/
`policy_refs` as new keys rather than replacing the existing four. Checked
every caller of `TransactionProcessorService::process()` first
(`StreamTransactionsJob`, `ProcessStreamJob`, `WatchTransactions`,
`AnalyzeTransaction`) — none read anything but `source`/`is_threat`/
`message`/`elapsed_ms`, so nothing could break. Cache-hit reads use `??`
fallbacks (`risk_level` defaults to high/low from `is_threat`, `narrative`
defaults to `message`, `confidence`/`policy_refs` default to null/empty)
specifically so vectors cached *before* this change still serve correctly
— an already-warm production cache doesn't need to be flushed or
backfilled. Ran the full Sentinel-L7 suite (312 tests) before and after;
added 4 new tests covering all three source paths (cache_hit-with-grading,
cache_hit-without-grading via the `??` fallback, cache_miss, fallback) —
zero regressions.

### Decision: Rule-based fallback derives risk_level rather than leaving it null

The Tier 3 fallback path (`ThreatAnalysisService`) has no AI grading at
all — no genuine `risk_level` to report. Derived `high`/`low` from the
existing `is_threat` boolean (matching the `threat_level` convention
already used elsewhere in this same file for vector-cache metadata) rather
than leaving `risk_level` null, so the adapter's `label` field is never
missing regardless of which of the three pipeline paths served a given
call — `confidence` stays null→0.0 in this path instead, since that's a
genuinely absent signal, not a derivable one.

### Challenge: `EvalPrediction.confidence` is non-optional, but Sentinel-L7's confidence can be null

Sentinel-L7's fallback path has no confidence score at all. Mapping
`None -> 0.0` in the adapter (documented inline) avoids widening
`EvalPrediction.confidence` to `float | None` just to accommodate one
service's one code path — that type change would ripple into
`harness.py`'s precision/recall math and the `harness_metric_gauge`
readings for every system-under-test, not just this one.
