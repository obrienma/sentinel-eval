# sentinel-eval

A standalone AI evaluation framework for scoring the outputs of services in
the Rhizome-Praetor suite — currently **Sentinel-L7** (`ComplianceDriver`
compliance/AML verdicts) and **Synapse-L4** (`Axiom` telemetry validation).
It is not embedded in either service: the harness knows nothing about
Sentinel or Synapse specifically, only about the normalized prediction
contract described below. See
[`docs/adr/0001-standalone-module.md`](docs/adr/0001-standalone-module.md)
for the full design rationale.

## The prediction contract

Every system-under-test is a callable that takes a raw input dict and
returns an `EvalPrediction`:

```python
class EvalPrediction(BaseModel):
    id: str                        # source_id / correlation token
    raw_output: dict[str, Any]     # untouched domain payload, for debugging
    label: str                     # normalized outcome — e.g. Sentinel's
                                    # risk_level or Synapse's status
    confidence: float
    metadata: dict[str, Any] = {}
```

`label` is a plain `str`, not a shared enum. Sentinel's `risk_level`
(`low|medium|high|critical|unknown`) and Synapse's `status`
(`nominal|degraded|critical`) are different taxonomies — forcing them into
one enum would leak one service's vocabulary into the harness. Each
system-under-test wrapper maps its own domain output into `label`; the
harness only ever compares `label` against ground truth for whichever
system it's currently scoring.

## Offline vs. online evaluation

### Offline (ground truth) — `sentinel_eval.harness.run_eval`

Runs a labeled dataset through a system-under-test and scores its
predictions against known-correct labels: precision/recall/F1 per label,
plus overall accuracy. **No LLM dependency anywhere in this path** — it
works even if every external model/service is down.

```python
from sentinel_eval.harness import run_eval
from sentinel_eval.models import EvalDataset

dataset = EvalDataset.model_validate({
    "examples": [
        {"input": {...}, "expected_label": "high"},
        ...
    ]
})

report = run_eval(my_system_under_test, dataset)
print(report.accuracy, report.per_label)
```

### Online (unlabeled, realistic traffic) — `sentinel_eval.online.*`

Production/sampled traffic has no ground truth, so it's scored by a
layered, cost-ordered pipeline instead. Each layer is more expensive (and
more speculative) than the last, and later layers are only meant to run on
what earlier layers flag as ambiguous — not on every item.

1. **`online/heuristics.py`** — rule-based checks (confidence thresholds,
   field-contradiction checks). Free, deterministic, always available.
   **Implemented.**
2. **`online/disagreement.py`** — cross-provider/cross-run disagreement
   (e.g. Sentinel-L7's dual Gemini/OpenRouter `ComplianceDriver`). Reuses
   infrastructure the system-under-test already has. **Scaffolded, not
   implemented.**
3. **`online/consistency.py`** — embedding-based consistency against
   Upstash Vector. Must call through the system-under-test's own embedding
   driver/config (e.g. Sentinel-L7's `EmbeddingService`), never a
   hardcoded model — Sentinel-L7 is mid-migration from 1536-dim Gemini
   embeddings to 768-dim `nomic-embed-text:v1.5`, and embedding
   independently here would cause Upstash dimension-mismatch errors the
   moment the two diverge. **Scaffolded, not implemented.**
4. **`online/judge.py`** — LLM-as-judge, reserved for the ambiguous tail
   flagged by layers 1–3. Best-effort only, behind a circuit breaker: try
   remote Ollama (over Tailscale) → on failure/timeout fall back to Gemini
   Flash free tier → on failure fall back to heuristics-only. Judge
   availability is tracked as its own metric
   (`JudgeMetrics.pct_scored_by_judge`) rather than hidden — a judge that
   silently falls back on every call is itself a signal worth seeing.
   **Circuit breaker scaffolded; Ollama/Flash calls are `TODO`.**

   This eval judge is distinct from Sentinel-L7's `prompts/synapse-l4-judge.md`,
   which scores `anomaly_score` for production routing — different purpose,
   different consumer. Before this judge is used to score unlabeled
   traffic, its verdicts should be validated against a labeled dataset via
   the offline `run_eval` path first.

## Plugging in a new system-under-test

Two real adapters exist under `src/sentinel_eval/adapters/`:

- **`synapse_l4.py`**: `make_synapse_l4_system_under_test()` POSTs to
  Synapse-L4's `/ingest` and maps its Axiom response into `EvalPrediction`
  (`status` → `label`, `anomaly_score` → `confidence`). Calls the real
  service over HTTP rather than importing its Python modules directly —
  see the module docstring for why (heavy service-specific dependencies,
  a Python-version mismatch, and an import-time config requirement that
  would all violate the standalone-module mandate).
- **`sentinel_l7.py`**: `make_sentinel_l7_system_under_test()` speaks
  MCP-over-HTTP directly to Sentinel-L7's `/mcp` endpoint (`analyze-transaction`
  tool) — a hand-rolled minimal JSON-RPC client for this one tool call,
  not the full `mcp` SDK. `risk_level` → `label`, `confidence` → `confidence`
  (`0.0` when Sentinel-L7's rule-based fallback path ran with no AI model
  involved, since `EvalPrediction.confidence` is non-optional). Required a
  small additive change to Sentinel-L7 itself
  (`TransactionProcessorService::process()` previously collapsed its full
  compliance grading down to a boolean `is_threat` before this tool could
  see it — `risk_level`/`narrative`/`confidence`/`policy_refs` are now
  surfaced too, verified backward-compatible against that repo's full test
  suite).

To wire up a new one:

1. Write a callable `(input: dict) -> EvalPrediction` that calls the target
   service and maps its domain output into the prediction contract above.
   Put the untouched domain payload in `raw_output` and a normalized
   outcome string in `label`.
2. For offline scoring: build an `EvalDataset` (see
   `tests/fixtures/compliance_dataset.json` for the shape) and call
   `run_eval(your_callable, dataset)`.
3. For online scoring: call `online.pipeline.evaluate_item(prediction, ...)`.
   It always runs heuristics first, then only escalates to
   disagreement/consistency/judge for predictions heuristics flags — and
   only for the layers whose dependency (`providers`, `embed_fn`, `judge`)
   you actually pass in. A layer you don't wire up is skipped, not an
   error.

## Observability

Every layer function and `evaluate_item` are wrapped in `@traced_layer(...)`
(`sentinel_eval.observability.decorators`), which is both a decorator and a
context manager — the same helper wraps `run_heuristics` as a whole
function and wraps individual attempts inside `JudgeCircuitBreaker.judge()`
as inline blocks (`ollama_attempt`, `flash_attempt`, `heuristics_fallback`),
so a Tempo trace for one scored item shows the full circuit-breaker path —
e.g. an Ollama timeout followed by a Gemini Flash success — not just the
final outcome.

Traces and metrics both export via OTLP/HTTP to
`${OTEL_EXPORTER_OTLP_ENDPOINT}/v1/traces` and `/v1/metrics`
(`OTEL_EXPORTER_OTLP_ENDPOINT` defaults to `http://localhost:4318`,
`OTEL_SERVICE_NAME` defaults to `sentinel-eval`) — the same Collector
endpoint EventHorizon and Synapse-L4 export to, so all three show up
distinctly in Grafana/Tempo. Metrics:

- `sentinel_eval.judge.outcome` (counter, labeled `source=ollama|flash|
  fallback`) — the "% scored by judge vs fallback" signal from
  `docs/adr/0001-standalone-module.md`.
- `sentinel_eval.layer.latency` (histogram, labeled `layer=...`) — per-layer
  latency for the four online layers.
- `sentinel_eval.harness.metric` (gauge, labeled `metric=precision|recall|
  f1|accuracy`, `label=<label>|overall`) — emitted once per `run_eval()`
  call, so a prompt/model change shows up as a step change in Grafana.

The SDK is initialized as an import-time side effect
(`sentinel_eval/observability/tracing.py`, `metrics.py`) rather than behind
a lazily-invoked init function — see that module's docstring for why:
Synapse-L4's current pattern (configuring OTel inside a FastAPI `lifespan`
handler, after the app and its routes are already constructed) is the
suspected cause of its trace-fragmentation bug, and this repo deliberately
avoids reproducing that ordering.

## Configuration

`src/sentinel_eval/config.py` holds env-var-with-default settings for
calling real systems-under-test (same style as `observability/_env.py`):
`SYNAPSE_L4_BASE_URL`, `SENTINEL_L7_MCP_URL`, `OLLAMA_JUDGE_HOST`/
`OLLAMA_JUDGE_MODEL` (remote, over Tailscale — LLM-as-judge only),
`OLLAMA_EMBEDDING_HOST`/`OLLAMA_EMBEDDING_MODEL` (local — mirrors
Sentinel-L7's own embedding host, a deliberately different machine from
the judge's), and `GEMINI_API_KEY`/`GEMINI_FLASH_URL` (same env var names
Sentinel-L7 uses, so one value covers both services).

## Development

```bash
uv sync                 # install dependencies
uv run pytest           # run the test suite
```

Running the test suite without a local OTel Collector at
`localhost:4318` is expected to print harmless "connection refused" retry
warnings on process exit — the same "additive observability" posture
Synapse-L4 already uses (instrumentation degrades gracefully; it never
affects correctness). No timeout override is configured, matching
EventHorizon's and Synapse-L4's exporters, both of which also rely on SDK
defaults.
