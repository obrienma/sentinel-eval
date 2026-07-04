---
type: cloze
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, mcp-jsonrpc]
---
Laravel MCP tool names are derived via `{{c1::Str::kebab}}(class_basename($this))`
by default — `AnalyzeTransaction` becomes the JSON-RPC tool name
`{{c2::analyze-transaction}}`, not the snake_case `analyze_transaction`
that appears only in the server's human-readable instructions text.

Extra: sentinel-eval · (verified against vendor/laravel/mcp source, not the MCP spec in general)
See: docs/journal/sentinel-eval-2026-07-04T0819-sentinel-l7-adapter.md

---
type: cloze
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, mcp-jsonrpc]
---
A Laravel MCP tool's JSON-RPC result content is `Response::json($result)`,
which is itself `json_encode($result)` wrapped in a text block — so
`result.content[0].text` must be {{c1::json.loads()}}-ed a second time to
reach the real payload.

Extra: sentinel-eval · Challenge: double-encoded MCP tool result
See: docs/journal/sentinel-eval-2026-07-04T0819-sentinel-l7-adapter.md

---
type: basic
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, additive-change]
---
Q: Why was `TransactionProcessorService::process()` changed to add
risk_level/narrative/confidence/policy_refs, and how was backward
compatibility with an already-warm production vector cache preserved?

A: The only real Sentinel-L7 integration surface (the AnalyzeTransaction
MCP tool) only ever exposed a boolean is_threat — risk_level was computed
internally from ComplianceDriver::analyzeTransaction() but discarded
before reaching any caller. Widening the summary() output to include the
full grading let the eval adapter score against the real risk_level
taxonomy instead of a boolean ceiling. Backward compatibility: cache-hit
reads use `??` fallbacks (risk_level defaults from is_threat, narrative
defaults to message, confidence/policy_refs default to null/empty) so
vectors cached before this change — which have no risk_level key at all —
still serve correctly without any cache flush or backfill.

Extra: sentinel-eval · Decision: Additive-only change, verified against the full existing test suite
See: docs/journal/sentinel-eval-2026-07-04T0819-sentinel-l7-adapter.md

---
type: cloze
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, backward-compatibility]
---
`EvalPrediction.confidence` is typed as a non-optional `{{c1::float}}`, so
when Sentinel-L7's rule-based fallback path returns a null confidence
(no AI model was involved), the Sentinel-L7 adapter maps it to
`{{c2::0.0}}` rather than widening the shared model to `float | None` for
one service's one code path.

Extra: sentinel-eval · Challenge: EvalPrediction.confidence is non-optional, but Sentinel-L7's confidence can be null
See: docs/journal/sentinel-eval-2026-07-04T0819-sentinel-l7-adapter.md
