# sentinel-eval

A standalone AI evaluation framework for scoring the outputs of services in
the Rhizome-Praetor suite — currently **Sentinel-L7** (`ComplianceDriver`
compliance/AML verdicts) and **Synapse-L4** (`Axiom` telemetry validation).
It is not embedded in either service: the harness knows nothing about
Sentinel or Synapse specifically, only about the normalized prediction
contract described below. See
[`docs/adr/0001-standalone-module.md`](docs/adr/0001-standalone-module.md)
for the full design rationale.

---

```mermaid
flowchart LR
    subgraph Offline["Offline (ground truth)"]
        F[Fixture JSON] --> H[run_eval]
        H --> R[EvalReport]
    end
    subgraph Online["Online (unlabeled traffic)"]
        P[EvalPrediction] --> L1[heuristics]
        L1 -->|flagged| L2[disagreement]
        L1 -->|flagged| L3[consistency]
        L1 -->|flagged| L4[judge]
        L2 --> O[OnlineScoringResult]
        L3 --> O
        L4 --> O
    end
    CLI[sentinel-eval CLI] --> H
```

---

## 📋 Contents

- [📋 Contents](#-contents)
- [🧰 Stack](#-stack)
- [🚀 Running the Project](#-running-the-project)
  - [✅ Prerequisites](#-prerequisites)
  - [⚡ Quick Start](#-quick-start)
  - [📦 CLI Reference](#-cli-reference)
- [🏗️ Architecture](#️-architecture)
  - [📐 The Prediction Contract](#-the-prediction-contract)
  - [🔀 Offline vs Online Evaluation](#-offline-vs-online-evaluation)
  - [🔌 Plugging in a New System-Under-Test](#-plugging-in-a-new-system-under-test)
- [📊 Benchmark Results](#-benchmark-results)
- [🔭 Observability](#-observability)
- [🔧 Configuration](#-configuration)
- [📚 Docs](#-docs)
- [🗺️ Roadmap](#️-roadmap)
  - [📋 Planned](#-planned)
  - [🐛 Known Issues](#-known-issues)
  - [🏁 Completed (Phase 3)](#-completed-phase-3)


## 🧰 Stack

**🐍 Core**

- **Python 3.12 + `uv`:** dependency management and the venv, same role `composer`/`npm` play in the sibling Sentinel-L7/Synapse-L4 repos.
- **Pydantic 2.9:** the entire cross-system contract (`EvalPrediction`, `EvalDataset`, `EvalReport`) is typed models, not dicts — see [📐 The Prediction Contract](#-the-prediction-contract).

**🌐 Integrations**

- **httpx:** adapters speak MCP-over-HTTP directly to Sentinel-L7's `/mcp` endpoint and REST to Synapse-L4's `/ingest` — no service SDK, no shared import boundary (ADR-0001).
- **Ollama + Gemini Flash + Upstash Vector:** the online layers' real infrastructure — Ollama for embeddings and the LLM-as-judge, Gemini Flash as the judge's fallback, Upstash Vector for the embedding-consistency layer.

**🔭 Observability**

- **OpenTelemetry:** traces + metrics exported via OTLP/HTTP to the same Collector endpoint Sentinel-L7/Synapse-L4/EventHorizon export to.

**🧪 Testing**

- **pytest + respx:** every external call in the automated suite is mocked at the HTTP boundary — this repo's suite never hits a real API, matching the "never hit real external APIs in tests" rule.


## 🚀 Running the Project

### ✅ Prerequisites

- **Python 3.12+** with `uv`
- Nothing else for `uv sync` / `uv run pytest` — every external call in the automated suite is mocked at the HTTP boundary.
- **Optional, live verification only:** a running Sentinel-L7 and/or Synapse-L4 instance, a reachable Ollama host (embedding + judge), a Gemini API key (judge fallback), Upstash Vector credentials (consistency layer) — see [🔧 Configuration](#-configuration).

> [!NOTE]
> Developed on **WSL2 (Ubuntu)**. Other environments may work but are untested.

### ⚡ Quick Start

```bash
# 1. Install dependencies
uv sync

# 2. Run the automated test suite (no live services required)
uv run pytest

# 3. Score a fixture against a real Sentinel-L7 instance
uv run sentinel-eval --system sentinel-l7 \
  --fixture tests/fixtures/sentinel_l7_ground_truth.json \
  --driver ollama --binary --limit 25
```

> [!TIP]
> For the full live-verification walkthrough — starting local
> Sentinel-L7/Synapse-L4 servers, exercising every online layer by hand,
> expected output for each step — see
> [`docs/DEV_GETTING_STARTED.md`](docs/DEV_GETTING_STARTED.md).

### 📦 CLI Reference

`sentinel-eval` (a `[project.scripts]` entry point,
`sentinel_eval.cli:main`) runs the offline harness from the shell against a
real adapter — no code required for a one-off scoring run. There is
deliberately no CLI surface for the online path
(`online.pipeline.evaluate_item`) — it's meant to be wired into a caller's
own sampling/production loop (which providers/embed_fn/judge to pass in is
a per-deployment decision), not run as a one-shot command the way a
labeled-fixture score is.

| Command / Flag | Description |
| --- | --- |
| `uv run pytest` | Run the full automated test suite (mocked HTTP boundary, no live services required) |
| `uv run sentinel-eval --system {sentinel-l7,synapse-l4}` | Score a fixture against a real adapter (required) |
| `--fixture PATH` | Labeled `EvalDataset` JSON whose `input` shape matches the chosen adapter's contract (required) |
| `--driver {gemini,openrouter,ollama}` | Sentinel-L7 only — force a specific `ComplianceManager` driver via the per-request override, bypassing the semantic cache |
| `--binary` | Sentinel-L7 only — collapse a predicted label to `'high'` unless it's exactly `'low'`, matching `TransactionProcessorService::gradeAiResult()` |
| `--url URL` | Override the configured base/MCP URL (defaults to `config.py`'s env-var-with-default) |
| `--limit N` | Only score the first N examples of the fixture |
| `--json` | Print the `EvalReport` as JSON instead of a text table |

A connection failure prints a one-line error to stderr and exits `1`
rather than a raw traceback.

**Live-verified**: run against a temporarily-started local Sentinel-L7
server with `--driver ollama` (bypassing the semantic cache) — a live item
scored correctly (`accuracy: 1/1 (100.0%)`). A larger batch surfaced a real
timeout on a slower Ollama response (a single driver-override call has
been observed to take anywhere from ~4.7s to timing out past the
adapter's default 10s) — the CLI's
`httpx.ConnectError`/`TimeoutException` handling caught it and exited `1`
with a friendly message rather than crashing, exercising that path against
a genuine failure, not a mock. Full steps, exact commands, and expected
output for every one of these live checks are in
[`docs/DEV_GETTING_STARTED.md`](docs/DEV_GETTING_STARTED.md).


## 🏗️ Architecture

### 📐 The Prediction Contract

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

### 🔀 Offline vs Online Evaluation

#### Offline (ground truth) — `sentinel_eval.harness.run_eval`

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

Two fixtures ship under `tests/fixtures/`: `compliance_dataset.json`
(hand-written, 15 examples) and `sentinel_l7_ground_truth.json` (200
examples, generated from Sentinel-L7's real pre-AI simulation profiles via
`php artisan sentinel:export-ground-truth` — see that repo's
`app/Console/Commands/ExportGroundTruth.php`). The latter's `expected_label`
is only ever `'high'`/`'low'` — ground truth pre-AI only knows a binary
threat flag, not a graded `risk_level` — so scoring Sentinel-L7 predictions
against it should collapse `medium`/`critical` into `'high'` the same way
`TransactionProcessorService::gradeAiResult()` does internally
(`is_threat = risk_level != 'low'`), rather than penalizing a correctly-
caught threat just because it landed on a different severity than `'high'`.

#### Online (unlabeled, realistic traffic) — `sentinel_eval.online.*`

Production/sampled traffic has no ground truth, so it's scored by a
layered, cost-ordered pipeline instead. Each layer is more expensive (and
more speculative) than the last, and later layers are only meant to run on
what earlier layers flag as ambiguous — not on every item.

| Layer | File | Status | Purpose |
| --- | --- | --- | --- |
| 1. Heuristics | `online/heuristics.py` | ✅ Implemented | Rule-based checks (confidence thresholds, field-contradiction checks). Free, deterministic, always available. |
| 2. Disagreement | `online/disagreement.py` | ✅ Implemented, live-verified | Cross-provider/cross-run disagreement (e.g. Sentinel-L7's dual Gemini/OpenRouter `ComplianceDriver`). |
| 3. Consistency | `online/consistency.py` | ✅ Implemented, live-verified | Embedding-based consistency against Upstash Vector's `transactions` namespace. |
| 4. Judge | `online/judge.py` | ✅ Implemented, live-verified, validated | LLM-as-judge behind a circuit breaker (Ollama → Gemini Flash → heuristics-only), reserved for the ambiguous tail. |

**2. Disagreement** — reuses infrastructure the system-under-test already
has. `score_disagreement()` calls each named provider with the same input
and compares labels; a provider call that raises is captured in
`errors_by_provider` rather than dropped, and `agreed` is only `True` when
every provider answered with the exact same label — an error makes
agreement unknowable, not automatically true. Uses Sentinel-L7's
per-request driver override (Phase 3 step 6):
`adapters.sentinel_l7.make_sentinel_l7_system_under_test(driver=...)`
builds one callable per provider, each bypassing the semantic cache so the
comparison is never contaminated by a different provider's cached verdict.
Live-verified against a real local Sentinel-L7 server: Ollama returned a
real verdict; OpenRouter and Gemini both genuinely failed (OpenRouter's
configured free model was retired upstream — a 404 "No endpoints found";
Gemini hit the same free-tier quota exhaustion seen validating the judge
layer) and both were correctly surfaced in `errors_by_provider` rather
than silently swallowed or crashing the comparison — exercising the error
path against real external failures, not just mocks.

**3. Consistency** — `make_ollama_embed_fn()` calls Sentinel-L7's own
local Ollama host/model/task-prefix convention exactly (verified against
`OllamaEmbeddingDriver::embed()` directly), never a hardcoded model —
Sentinel-L7's live config has `SENTINEL_EMBEDDING_DRIVER=ollama`, 768-dim
`nomic-embed-text:v1.5`, and embedding independently here would cause
Upstash dimension-mismatch errors the moment the two diverge.
`query_upstash_vector()` mirrors `VectorCacheService::searchNamespace()`'s
exact request shape. **Implemented and live-verified**: a real embed call
against the actual Ollama host returned a 768-dim vector, and a real
Upstash Vector query against the live index succeeded (0 matches,
confirmed correct via the index's own `/info` endpoint — the
`transactions` namespace has no vectors yet in this dev environment, so an
empty result is the right answer, not a bug).

**4. Judge** — best-effort only, behind a circuit breaker: try remote
Ollama (over Tailscale) → on failure/timeout fall back to Gemini Flash
free tier → on failure fall back to heuristics-only. Judge availability is
tracked as its own metric (`JudgeMetrics.pct_scored_by_judge`) rather than
hidden — a judge that silently falls back on every call is itself a
signal worth seeing. Both calls force strict-JSON output at the API level
(Ollama's `"format": "json"`, Gemini's `generationConfig.responseMimeType`)
and load their shared prompt from `prompts/judge.txt` (versioned in
`prompts/judge.md`, mirroring Sentinel-L7's `prompts/*.md`+`*.txt`
convention) rather than hardcoding the prompt text inline. A real call
against the Tailscale Ollama host (`qwen3.5:9b-q4_K_M`) returned a genuine
verdict in ~12s; a real call to Gemini Flash correctly raised
`httpx.HTTPStatusError` on a live 429 (free-tier quota exhausted),
confirming the fail-through contract holds against a real failure, not
just a mocked one.

This eval judge is distinct from Sentinel-L7's
`prompts/synapse-l4-judge.md`, which scores `anomaly_score` for production
routing — different purpose, different consumer. Before this judge is
used to score unlabeled traffic, its verdicts should be validated against
a labeled dataset via the offline `run_eval` path first. An early attempt
against `tests/fixtures/compliance_dataset.json` scored only 6.7%
accuracy, but inspection showed the judge reasoning correctly and just
answering in the *wrong taxonomy* — that fixture's `raw_output` is
Synapse-shaped (`status`/`anomaly_score`) while its `expected_label` is
Sentinel's `risk_level` vocabulary, a mismatch invisible to `run_eval()`
(which never inspects `raw_output`, only compares `label`) until something
reasoned over the raw fields directly. **Validated** as of Phase 3 step 8
against the taxonomy-consistent `sentinel_l7_ground_truth.json` fixture
instead — see [📊 Benchmark Results](#-benchmark-results) below.

### 🔌 Plugging in a New System-Under-Test

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
  suite). Also takes an optional `driver` parameter (`'gemini'`/`'openrouter'`/
  `'ollama'`) that forces Sentinel-L7's per-request `ComplianceManager`
  override instead of its app-wide default — building one instance per
  provider is how `online.disagreement.score_disagreement` gets independent,
  cache-bypassing verdicts for the same transaction.

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


## 📊 Benchmark Results

Live-verification runs against real services, not mocks. The Journal column
links to the entry with full methodology (sample composition, seed, raw
per-item output).

| Date | Fixture | System | Sample | Strict accuracy | Binary accuracy | Notes | Journal |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-07-04 | `sentinel_l7_ground_truth.json` | Sentinel-L7 (`driver=ollama`, cache bypassed) | 25 live / 200 (all 10 `high` + 15 random `low`, seed 42) | 84% | **92%** | First attempt (no driver override) scored 52% — a real semantic-cache amplification bug, not a model failure; tracked as a Known Issue in sentinel-l7's own README. | [step 8](docs/journal/sentinel-eval-2026-07-04T1720-ground-truth-export-and-judge-validation.md) |
| 2026-07-04 | `sentinel_l7_ground_truth.json` | Judge (`qwen3.5:9b-q4_K_M` via Ollama) | Same 25, called unconditionally (bypassing the heuristic gate) | 80% | **92%** | 2/25 verdicts were non-taxonomy tokens (`"reject"`, `"correct"`) instead of a label — a prompt-following gap, not yet fixed. | [step 8](docs/journal/sentinel-eval-2026-07-04T1720-ground-truth-export-and-judge-validation.md) |
| 2026-07-04 | `compliance_dataset.json` | Judge (`qwen3.5:9b-q4_K_M` via Ollama) | All 15 | 6.7% | — | Fixture defect, not a judge failure: `raw_output` is Synapse-shaped, `expected_label` is Sentinel-shaped — the judge answered correctly in the wrong taxonomy. Superseded by the row above; kept here as a documented false alarm. | [step 5](docs/journal/sentinel-eval-2026-07-04T1512-judge-layer.md) |

**Strict vs. binary**: `sentinel_l7_ground_truth.json`'s `expected_label` is
only ever `'high'`/`'low'` (ground truth pre-AI knows only a boolean threat
flag — see [🔀 Offline vs Online Evaluation](#-offline-vs-online-evaluation)
above). *Strict* compares the predicted label string exactly; *binary*
collapses `medium`/`high`/`critical` to `'high'` first
(`is_threat = risk_level != 'low'`, matching
`TransactionProcessorService::gradeAiResult()`). Binary is the number that
reflects what this ground truth can actually justify claiming — a
`critical` verdict on a real threat is a correct catch, not a miss, and
strict accuracy alone would misrepresent that as a failure.


## 🔭 Observability

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


## 🔧 Configuration

`src/sentinel_eval/config.py` holds env-var-with-default settings for
calling real systems-under-test (same style as `observability/_env.py`):
`SYNAPSE_L4_BASE_URL`, `SENTINEL_L7_MCP_URL`, `OLLAMA_JUDGE_HOST`/
`OLLAMA_JUDGE_MODEL` (remote, over Tailscale — LLM-as-judge only),
`OLLAMA_URL`/`OLLAMA_EMBEDDING_MODEL` (same env var names as Sentinel-L7's
own embedding config — in this environment both `OLLAMA_JUDGE_HOST` and
`OLLAMA_URL` happen to point at the same Tailscale host, since one Ollama
instance serves both the judge and embedding models here, but they're
independent settings), `GEMINI_API_KEY`/`GEMINI_FLASH_URL` (same env var
names Sentinel-L7 uses, so one value covers both services), and
`UPSTASH_VECTOR_REST_URL`/`UPSTASH_VECTOR_REST_TOKEN`/
`UPSTASH_VECTOR_THRESHOLD` (same env var names and default threshold as
Sentinel-L7's `config/services.php` — no default URL/token, since those
are account-specific secrets).


## 📚 Docs

| File | Contents |
| --- | --- |
| [README.md](README.md) | Project overview |
| [docs/adr/0001-standalone-module.md](docs/adr/0001-standalone-module.md) | Why sentinel-eval is standalone, not embedded in Sentinel-L7 |
| [docs/DEV_GETTING_STARTED.md](docs/DEV_GETTING_STARTED.md) | Full live-verification walkthrough — manual tests against real Sentinel-L7/Synapse-L4/online-layer infrastructure |
| [docs/journal/](docs/journal/) | Engineering journal — one entry per phase/step |
| [docs/probes/](docs/probes/) | Paired Anki spaced-repetition probe cards, one file per journal entry |
| [prompts/judge.md](prompts/judge.md) | Judge prompt — versioned Markdown, changelog, `Used by:` list |


## 🗺️ Roadmap

### 📋 Planned

- [ ] **CLI surface for the online layers** — deliberately deferred; wiring providers/`embed_fn`/judge is a per-deployment decision (see [📦 CLI Reference](#-cli-reference)), not a one-shot command.
- [ ] **Judge prompt-following fix** — `qwen3.5` occasionally emits non-taxonomy tokens (`"reject"`, `"correct"`) instead of a label (2/25 in the step 8 live sample); flagged in `prompts/judge.txt`, not yet fixed.
- [ ] **A Synapse-L4-shaped fixture for `tests/fixtures/`** — no ground truth exists yet for Axiom extraction correctness (ADR-0001 flags this as unsolved, out of scope for Phase 3).

### 🐛 Known Issues

- **Ollama driver-override latency can exceed the adapter's default 10s timeout.** A single Sentinel-L7 `--driver ollama` call has been observed to take anywhere from ~4.7s to past 10s against the real model — occasionally crossing the adapter's default per-request timeout and surfacing as a genuine `httpx.TimeoutException`. Not a bug in the CLI's error handling, which catches it correctly; see `docs/DEV_GETTING_STARTED.md`.
- **`compliance_dataset.json` isn't adapter-compatible.** Its `input` shape doesn't match either adapter's real request contract (Synapse-shaped fields flattened, missing the `source_id`/`payload` envelope). Use `sentinel_l7_ground_truth.json` for real adapter runs; `compliance_dataset.json` is retained only as a hand-written judge-prompt smoke fixture.
- **Sentinel-L7's own semantic cache can amplify a single wrong verdict for narrow-profile merchants.** Not a sentinel-eval bug, but it affects online-layer/CLI runs against Sentinel-L7 whenever `--driver` isn't forced — see Sentinel-L7's own README Known Issues.

### 🏁 Completed (Phase 3)

<details>
<summary>🔍 View shipped steps...</summary>

1. Foundational `config.py` + `httpx` dependency
2. Synapse-L4 HTTP adapter (`adapters/synapse_l4.py`)
3. Sentinel-L7 MCP-over-HTTP adapter (`adapters/sentinel_l7.py`) — required a paired additive widening of Sentinel-L7's `TransactionProcessorService::process()`
4. Embedding consistency layer (`online/consistency.py`) — live-verified against a real Ollama host and Upstash Vector index
5. LLM-as-judge layer (`online/judge.py`, `prompts/judge.md`+`.txt`) — live-verified against real Ollama and Gemini Flash calls
6. Sentinel-L7 per-request driver override (cross-repo, sentinel-l7 only — bypasses the semantic cache for fresh, cross-provider verdicts)
7. Cross-provider disagreement layer (`online/disagreement.py`) — live-verified, including genuine external provider failures
8. Ground-truth export command + taxonomy-consistent fixture (`sentinel_l7_ground_truth.json`) — closed the judge-validation gate (92% binary accuracy for both Sentinel-L7 and the judge)
9. CLI entrypoint (`sentinel-eval` console script) — offline harness only, live-verified against a real local Sentinel-L7 server

</details>
