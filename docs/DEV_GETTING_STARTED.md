# arbiter-l8 — Developer Getting-Started Guide

Everything below was actually run against real services to confirm it
works, not just asserted — every command here was re-run while writing
this guide. Use it as the exhaustive step-by-step checklist for confirming
a fresh checkout actually works end to end, not just that `pytest` is
green. For the short version, see the main [README](../README.md#-quick-start)'s
Quick Start.

## 0. Setup

```bash
uv sync
```

Env vars used below (all have dev-environment defaults in
`src/arbiter_l8/config.py` — see the README's
[🔧 Configuration](../README.md#-configuration) section):
`SENTINEL_L7_MCP_URL`, `SYNAPSE_L4_BASE_URL`, `OLLAMA_URL`,
`OLLAMA_EMBEDDING_MODEL`, `OLLAMA_JUDGE_HOST`, `OLLAMA_JUDGE_MODEL`,
`GEMINI_API_KEY`, `UPSTASH_VECTOR_REST_URL`, `UPSTASH_VECTOR_REST_TOKEN`.
None are required just to run the automated test suite (step 1) — they
only matter for the live steps below.

## 1. Automated suite

```bash
uv run pytest -v
```

Expect all tests passing (77 as of the `synapse_l4_ground_truth.json` fixture, step 12). The "connection refused"
OTel warnings on exit are expected without a local Collector at
`:4318` — instrumentation degrades gracefully and never affects
correctness (same posture Synapse-L4 uses).

## 2. CLI against a real Sentinel-L7 server

Requires a checked-out, configured Sentinel-L7 (`~/dev/sentinel-l7` in this
environment — see that repo's own README/CLAUDE.md for its env setup:
`GEMINI_API_KEY`, `OLLAMA_URL`, DB migrations, etc.).

```bash
# terminal 1 — from the sentinel-l7 checkout
cd ~/dev/sentinel-l7
php artisan serve --port=8080
```

```bash
# terminal 2 — health check before trusting anything the CLI reports
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/mcp \
  -X POST -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"analyze-transaction","arguments":{"amount":10,"currency":"USD","merchant":"Test"}}}'
# expect: 200
```

```bash
# terminal 2 — from this repo, scoring one real example with the
# driver override (bypasses the semantic cache so it's a fresh verdict)
cd ~/dev/arbiter-l8
SENTINEL_L7_MCP_URL=http://127.0.0.1:8080/mcp uv run arbiter-l8 \
  --system sentinel-l7 \
  --fixture tests/fixtures/sentinel_l7_ground_truth.json \
  --driver ollama --binary --limit 1 --json
```

Expect a JSON `EvalReport` with `"accuracy": 1.0` and one prediction whose
`raw_output.source` is `"driver_override"`. **Observed real latency: a
single driver-override call has taken anywhere from ~4.7s to timing out
past the adapter's default 10s** — if you see
`error: could not reach sentinel-l7 — timed out`, that's real Ollama
latency variance, not a CLI bug; just re-run.

Confirm the plain-text report path too, and try a larger sample:

```bash
uv run arbiter-l8 --system sentinel-l7 \
  --fixture tests/fixtures/sentinel_l7_ground_truth.json \
  --driver ollama --limit 5
```

Note: omitting `--driver` lets Sentinel-L7 use its app-wide default and its
semantic cache — repeated runs against a narrow-profile merchant can then
return `cache_hit` for every item (a real amplification effect documented
in the README's [📊 Benchmark Results](../README.md#-benchmark-results),
not a CLI bug). Use `--driver` whenever you want a guaranteed fresh,
cache-bypassing verdict.

Confirm the error path by stopping the server (`Ctrl+C` in terminal 1)
and re-running the same command:

```bash
uv run arbiter-l8 --system sentinel-l7 \
  --fixture tests/fixtures/sentinel_l7_ground_truth.json --limit 1
echo "exit code: $?"
```

Expect stdout empty, stderr
`error: could not reach sentinel-l7 — [Errno 111] Connection refused`,
and exit code `1`.

Stop the server for good afterward (`Ctrl+C`, or
`pkill -f "php artisan serve --port=8080"`) — it's a temporary process for
this verification only, not a persistent service.

## 3. CLI against a real Synapse-L4 server

Synapse-L4 needs a reachable Redis (`SENTINEL_REDIS_URL`) and an LLM key
(`OPENAI_API_KEY` or `ANTHROPIC_API_KEY`) before it will even boot — see
`~/dev/synapse-l4/.env.example`.

```bash
# terminal 1 — from the synapse-l4 checkout
cd ~/dev/synapse-l4
uv run fastapi dev main.py   # serves on :8000
```

```bash
# terminal 2 — health check
curl -s -X POST http://127.0.0.1:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{"source_id": "manual-check-1", "payload": {"metric": "test"}}'
```

`tests/fixtures/synapse_l4_ground_truth.json` (12 examples) is shaped for
Synapse-L4's real `{source_id, payload}` contract — unlike
`compliance_dataset.json`, whose `input` is flattened, not that envelope.
Run the whole thing as a batch:

```bash
# terminal 2 — from this repo
cd ~/dev/arbiter-l8
uv run arbiter-l8 --system synapse-l4 \
  --fixture tests/fixtures/synapse_l4_ground_truth.json --json
```

Expect `"accuracy": 1.0`, `12/12`. Every example uses the "EventHorizon raw
document" fast path (`raw.payload.status`/`processed.classification`, no
LLM call) — the `expected_label` for each was computed by hand directly
from `extract()`'s `_try_direct_extraction` mapping table, not guessed;
see the README's fixtures section for why that's legitimate ground truth
here despite ADR-0001 still flagging real LLM-extraction ground truth as
unsolved. **Live-verified**: this exact run scored `12/12 (100.0%)`.

Every fixture example deliberately avoids a real contradiction trap
in that same mapping table — `status: "passed"`/`"success"` paired with
`classification: "warning"`/`"critical"` deterministically produces a
self-contradictory draft that the Judge stage rejects. Confirmed live:

```bash
cat > /tmp/synapse_fastpath_trap.json <<'EOF'
{"examples": [{"input": {"source_id": "fastpath-trap-1", "payload": {"raw": {"payload": {"status": "passed", "durationMs": 50}}, "processed": {"classification": "critical"}}}, "expected_label": "critical"}]}
EOF

uv run arbiter-l8 --system synapse-l4 \
  --fixture /tmp/synapse_fastpath_trap.json --limit 1 --json
echo "exit code: $?"
```

Expect the same `422 judge_rejected` shape as the LLM-path error case
below, exit code `1` — this one requires no LLM at all to reproduce. See
the README's [🐛 Known Issues](../README.md#-known-issues); not a
arbiter-l8 bug, Synapse-L4's own code, out of scope to fix here.

For a single-example smoke test instead, write a one-off fixture. This one
uses the same fast path (`status`/`metric_value`/`anomaly_score` already
present in `payload`, the "already-shaped" variant rather than the
EventHorizon-raw-document one above), so it also skips the LLM call:

```bash
cat > /tmp/synapse_smoke.json <<'EOF'
{"examples": [{"input": {"source_id": "manual-1", "payload": {"status": "degraded", "metric_value": 87.3, "anomaly_score": 0.62, "domain": "aml"}}, "expected_label": "degraded"}]}
EOF

# terminal 2 — from this repo
cd ~/dev/arbiter-l8
uv run arbiter-l8 --system synapse-l4 \
  --fixture /tmp/synapse_smoke.json --limit 1 --json
```

Expect a JSON `EvalReport` with `"accuracy": 1.0`, `raw_output.source_id`
matching the fixture, and `metadata.pipeline_ms` reflecting the real round
trip (extraction + judge + a real `XADD` to Sentinel-L7's `synapse:axioms`
Redis stream). **Live-verified**: this exact run scored `1/1 (100.0%)` with
`pipeline_ms: 1340`.

Confirm the real LLM path too — a payload with no `status`/`metric_value`/
`anomaly_score` fields forces the fast path to miss and falls through to a
real Instructor/Ollama call (`qwen3.5:9b-q4_K_M`, ~14s observed):

```bash
cat > /tmp/synapse_smoke_llm.json <<'EOF'
{"examples": [{"input": {"source_id": "manual-llm-1", "payload": {"message": "CPU utilization on payment-gateway-3 spiked to 96% for 4 minutes straight, well above the 80% alert threshold. Error rate also rose to 2.1%."}}, "expected_label": "critical"}]}
EOF

uv run arbiter-l8 --system synapse-l4 \
  --fixture /tmp/synapse_smoke_llm.json --limit 1 --json
```

The real model can extract a self-contradictory draft on its own (a real
run returned `anomaly_score: 0.87` with `status: "degraded"`, not
`"critical"`) — Synapse-L4's own rule-based Judge stage catches this
(`anomaly_score >= 0.8` requires `status == "critical"`) and the call
above will raise instead of printing a report; see the error-path note
below before assuming something is broken.

Confirm the error path — the fixture above (or the fast-path fixture with
`anomaly_score: 0.93`/`status: "nominal"`) reliably reproduces a real
`422 judge_rejected` from Synapse-L4:

```bash
uv run arbiter-l8 --system synapse-l4 \
  --fixture /tmp/synapse_smoke_llm.json --limit 1 --json
echo "exit code: $?"
```

Expect stdout empty, stderr
`error: Synapse-L4 /ingest failed (422): {'error': 'judge_rejected', ...}`,
and exit code `1` — `cli.py` catches both `SentinelL7Error` and
`SynapseL4Error` alongside the connection/timeout cases above, so a
rejected request prints a friendly one-liner rather than a raw traceback.
**Live-verified.**

Stop the server for good afterward (`Ctrl+C` in terminal 1) — it's a
temporary process for this verification only, not a persistent service.

## 4. Online layers (no CLI surface — by design)

These have no one-shot command; wiring them is a per-deployment decision
(see the README's [📦 CLI Reference](../README.md#-cli-reference)). Run
each snippet with `uv run python -c "..."` from this repo so the venv
resolves correctly.

**Embedding consistency** — needs `OLLAMA_URL` pointed at a host that
actually has the embedding model pulled. In this dev environment the
*default* `OLLAMA_URL` (`localhost:11434`) has no models pulled at all, and
even the Tailscale host's model is tagged `nomic-embed-text:v1.5`, not the
untagged `nomic-embed-text` `OLLAMA_EMBEDDING_MODEL` defaults to (a
documented drift) — both must be overridden together or you'll hit a real
`404 model not found`:

```bash
OLLAMA_URL=http://100.82.223.70:11434 \
OLLAMA_EMBEDDING_MODEL=nomic-embed-text:v1.5 \
uv run python -c "
from arbiter_l8.online.consistency import make_ollama_embed_fn, query_upstash_vector
embed = make_ollama_embed_fn()
vector = embed('a \$500 purchase at a grocery store')
print('embedding dim:', len(vector))            # expect 768
print(query_upstash_vector(vector))              # UpstashVectorError if creds unset — expected
"
```

**Disagreement** — needs a running local Sentinel-L7 (step 2 above):

```bash
uv run python -c "
from arbiter_l8.adapters.sentinel_l7 import make_sentinel_l7_system_under_test
from arbiter_l8.online.disagreement import score_disagreement
providers = {
    d: make_sentinel_l7_system_under_test(mcp_url='http://127.0.0.1:8080/mcp', driver=d)
    for d in ('ollama',)   # add 'gemini'/'openrouter' if those keys/quota are live
}
result = score_disagreement({'amount': 500, 'currency': 'USD', 'merchant': 'Test'}, providers)
print(result.agreed, result.labels_by_provider, result.errors_by_provider)
"
```

Expect `True {'ollama': 'low'} {}` for a low-risk merchant. Adding
`'gemini'`/`'openrouter'` to `providers` is expected to genuinely fail in
this dev environment (retired free model / exhausted free-tier quota — see
the README's [📊 Benchmark Results](../README.md#-benchmark-results)); a
populated `errors_by_provider` for those keys is the correct, verified
outcome, not a bug.

**Judge** — needs `OLLAMA_JUDGE_HOST` reachable (defaults to the Tailscale
host already used above):

```bash
uv run python -c "
from arbiter_l8.models import EvalPrediction
from arbiter_l8.online.judge import JudgeCircuitBreaker
prediction = EvalPrediction(id='t1', raw_output={'risk_level': 'high'}, label='high', confidence=0.4)
verdict = JudgeCircuitBreaker().judge(prediction, context='low confidence on a high verdict')
print(verdict.source, verdict.verdict_label)
"
```

Expect `JudgeSource.OLLAMA high` (or a similar taxonomy-consistent label)
on success; a slow/unreachable Ollama should fall through to Gemini Flash
and then heuristics-only per the circuit-breaker contract described in the
README's [🔀 Offline vs Online Evaluation](../README.md#-offline-vs-online-evaluation)
section.
