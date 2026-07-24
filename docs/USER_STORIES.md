# User Stories — Arbiter-L8

Stories are organised by domain. Each story is marked:

-   ✅ **Implemented** — delivered in the current codebase
-   🔲 **Aspirational** — not yet built; a TODO exists in code, the README Roadmap, or the linked ADR
-   🚫 **Deferred** — explicitly out of scope for this project; see the linked ADR

Each story is told from one of five actors:

-   🧪 **Evaluator** — runs offline benchmarks and one-off CLI scoring runs against ground truth
-   🤖 **ML Engineer** — operates and tunes the online escalation pipeline (heuristics/disagreement/consistency/judge)
-   🔗 **Integrator** — wires up adapters so a new system-under-test can be scored at all
-   🛠️ **Platform Engineer** — keeps observability and shared-infra export healthy
-   🧱 **Maintainer** — protects the architecture, contracts, and standalone boundary over time

Arbiter-L8 scores Sentinel-L7 and Synapse-L4 from *outside* their data path, through two **deliberately distinct** paths, not a duplicated one. Where they overlap (both ultimately produce a "how good was this verdict" signal) they measure *different regimes*: offline scoring is ground-truth-labeled and requires no LLM at all; online scoring is unlabeled production traffic, scored by a cost-ascending pipeline that only escalates to an LLM judge for the ambiguous tail. Both paths show up below, against the stories they satisfy.

---

## 🎯 Offline Evaluation (Ground Truth)

### ✅ 🎯 Score a system without any LLM in the loop

> As an 🧪 evaluator, I want to run a labeled dataset through a system-under-test and get precision/recall/F1 without any LLM online, so that the harness's core signal still works even if every external model is down.

*Delivered by:* `run_eval()` scores predictions against `expected_label` directly — no judge, no embedding call, no external dependency anywhere in this path (`src/arbiter_l8/harness.py`; ADR-0001)

---

### ✅ 🎯 Get a fair accuracy number when ground truth is coarser than the model

> As an 🧪 evaluator, I want a binary accuracy that collapses `medium`/`critical` into `high`, so that a model correctly catching a threat isn't penalized just for landing on a different severity than a ground truth that only knows a boolean threat flag.

*Delivered by:* `--binary` flag, matching `TransactionProcessorService::gradeAiResult()`'s `is_threat = risk_level != 'low'` (`src/arbiter_l8/cli.py`; README Benchmark Results)

---

### ✅ 🎯 Trust ground truth exported from the real system, not hand-guessed

> As an 🧪 evaluator, I want ground truth generated directly from Sentinel-L7's real pre-AI simulation profiles, so that scoring reflects actual system behaviour rather than fixtures I invented by hand.

*Delivered by:* `sentinel_l7_ground_truth.json` (200 examples) generated via `php artisan sentinel:export-ground-truth` (`tests/fixtures/`; README Phase 3 step 8)

---

### 🔲 🎯 Get ground truth for genuine LLM-driven extraction

> As an 🧪 evaluator, I want ground truth that covers Synapse-L4's real LLM-driven Axiom extraction, so that I can validate the harder, non-deterministic path — not only the rule-based fast path.

*TODO:* `synapse_l4_ground_truth.json` only covers `_try_direct_extraction`'s deterministic Shape 2 mapping; ADR-0001 explicitly flags real extraction-correctness ground truth as unsolved, out-of-scope follow-up (README Roadmap; ADR-0001 Consequences)

---

## 🧭 Online Escalation Pipeline

### ✅ 🧭 Only pay for a judge call on the ambiguous tail

> As an 🤖 ML engineer, I want unlabeled traffic scored by cheap, deterministic checks first, so that expensive judge calls only run on items cheaper layers couldn't resolve, keeping cost bounded.

*Delivered by:* `evaluate_item()` runs heuristics → disagreement → consistency → judge in cost-ascending order (`src/arbiter_l8/online/pipeline.py`; ADR-0002)

---

### ✅ 🧭 Degrade gracefully instead of failing when the judge is down

> As an 🤖 ML engineer, I want online scoring to fall back to a cheaper source rather than fail outright when the LLM judge is unreachable, so that a partner-owned host or a free-tier quota outage doesn't take down eval coverage entirely.

*Delivered by:* `JudgeCircuitBreaker` — Ollama → Gemini Flash → heuristics-only, each hop live-verified against a genuine failure (`src/arbiter_l8/online/judge.py`; ADR-0002)

---

### ✅ 🧭 Skip a layer I haven't wired up, rather than crash

> As an 🔗 integrator running a partial setup, I want a layer whose dependency (`providers`/`embed_fn`/`judge`) I didn't supply to be skipped, not treated as an error, so that I can exercise the pipeline during development without wiring all four layers at once.

*Delivered by:* dependency-gated escalation — a layer runs only when flagged **and** its dependency was supplied (`src/arbiter_l8/online/pipeline.py`; ADR-0002)

---

### ✅ 🧭 Never let a provider error masquerade as agreement

> As an 🤖 ML engineer, I want a provider call that raises during disagreement scoring captured separately from a real verdict, so that an error is never silently counted as "agreed."

*Delivered by:* `score_disagreement()`'s `errors_by_provider` — `agreed` is `True` only when every provider returns the identical label; live-verified against genuine OpenRouter/Gemini failures (`src/arbiter_l8/online/disagreement.py`)

---

### ✅ 🧭 Keep the consistency layer's embeddings from silently drifting out of sync

> As an 🤖 ML engineer, I want the consistency layer to call the exact embedding host/model Sentinel-L7 uses in production, so that Upstash Vector never rejects a write or query on a dimension mismatch.

*Delivered by:* `make_ollama_embed_fn()` mirrors `OllamaEmbeddingDriver::embed()` exactly, verified against a live 768-dim vector (`src/arbiter_l8/online/consistency.py`; ADR-0002)

---

### ✅ 🧭 See how much of the ambiguous tail is really being judged

> As an 🤖 ML engineer, I want the share of items scored by the judge vs. falling back to a cheaper source tracked as its own metric, so that a judge quietly falling back on every call is a visible signal, not a hidden one.

*Delivered by:* `arbiter_l8.judge.outcome` counter labeled `source=ollama|gemini_flash|heuristics_fallback` (`src/arbiter_l8/observability/metrics.py`)

---

### 🔲 🧭 Get a real before/after read on the judge prompt fix

> As an 🤖 ML engineer, I want the fixed judge prompt re-run across the full 25-item validation sample, so that I have a real before/after accuracy comparison rather than a single spot-check.

*TODO:* only one live spot-check has been run so far; the 92%/80% benchmark numbers on record still reflect the v1 prompt, before the prompt-following fix (README Roadmap)

---

### 🔲 🧭 Route the unresolved ambiguous tail to a human, not just a fallback label

> As an 🤖 ML Engineer, I want items where the judge fell through to heuristics-only, or where layers disagreed with each other, queued for human review instead of silently accepting the cheapest available answer, so that genuinely ambiguous cases get a human verdict rather than an LLM-availability artifact standing in for one.

*TODO:* no human-verdict store or review surface exists yet; `heuristics_fallback` is currently the terminal state for judge-unavailable items, not a queue entry (`src/arbiter_l8/online/judge.py`)

---

## 🔌 Adapters & Integration

### ✅ 🔌 Plug in a new system-under-test with one callable

> As an 🔗 integrator, I want to wrap a new service behind a single `(input) -> EvalPrediction` callable, so that the harness itself never needs Sentinel- or Synapse-specific code to score it.

*Delivered by:* the `EvalPrediction` contract plus `adapters/sentinel_l7.py` and `adapters/synapse_l4.py` as the two reference implementations (`src/arbiter_l8/models.py`; ADR-0001)

---

### ✅ 🔌 Score Sentinel-L7 through its real deployed contract, not a shortcut

> As an 🔗 integrator, I want to call Sentinel-L7's actual `/mcp` `analyze-transaction` tool over HTTP, so that the eval reflects what's really deployed, not an internal import shortcut.

*Delivered by:* a hand-rolled minimal JSON-RPC client speaking MCP-over-HTTP for this one tool call (`src/arbiter_l8/adapters/sentinel_l7.py`)

---

### ✅ 🔌 Get independent, cache-bypassing verdicts per provider

> As an 🔗 integrator, I want to force a specific `ComplianceManager` driver per request, so that cross-provider disagreement scoring is never contaminated by a different provider's cached verdict.

*Delivered by:* `sentinel_l7.py`'s `driver` parameter plus Sentinel-L7's own per-request override (required a small additive, backward-compatible change to `TransactionProcessorService::process()`) (`src/arbiter_l8/adapters/sentinel_l7.py`; README Phase 3 step 6)

---

### ✅ 🔌 Confirm a designed contradiction gets rejected, not silently passed

> As an 🔗 integrator, I want a fixture engineered to contradict itself run through Synapse-L4's real Extract → Judge → Emit pipeline, so that I can confirm the adapter surfaces a genuine rejection rather than a silently-passed bad verdict.

*Delivered by:* live-verified against a real local Synapse-L4 instance — a designed contradiction correctly triggered a real `422 judge_rejected` (`src/arbiter_l8/adapters/synapse_l4.py`; README "Plugging in a New System-Under-Test")

---

### 🚫 🔌 Import a service's modules directly instead of calling it over HTTP

> As an 🔗 integrator, I want to import Synapse-L4's Python modules directly for a faster, no-HTTP adapter, so that I skip the network hop entirely.

*Deferred:* rejected per the module docstring and ADR-0001 — heavy service-specific dependencies, a Python-version mismatch, and an import-time config requirement would all violate the standalone-module mandate (`src/arbiter_l8/adapters/synapse_l4.py`; ADR-0001)

---

## 📦 CLI & Developer Experience

### ✅ 📦 Score a fixture from the shell, no code required

> As an 🧪 evaluator, I want a one-off CLI command to score a fixture against a real Sentinel-L7/Synapse-L4 instance, so that I don't need to write a script for a single ad hoc run.

*Delivered by:* the `arbiter-l8` console script (`src/arbiter_l8/cli.py`, `arbiter_l8.cli:main` entry point)

---

### ✅ 📦 Get a friendly one-liner instead of a raw traceback

> As an 🧪 evaluator, I want connection failures and rejected requests to print a clear one-line error and exit `1`, so that a bad run doesn't dump a stack trace I have to parse.

*Delivered by:* the CLI catches `httpx.ConnectError`/`TimeoutException` and `SentinelL7Error`/`SynapseL4Error`, live-verified against a real timeout and a real `422` (`src/arbiter_l8/cli.py`; README Known Issues, Roadmap Phase 3 step 10)

---

### 🚫 📦 Run the online pipeline as a one-shot CLI command

> As an 🧪 evaluator, I want a CLI flag to run the online escalation layers the same way I run the offline harness, so that I don't have to write wiring code for a quick check.

*Deferred:* deliberately out of scope — which providers/`embed_fn`/judge to pass in is a per-deployment decision, not a one-shot command (README CLI Reference, Roadmap Planned)

---

## 🔭 Observability

### ✅ 🔭 Follow one scored item's full circuit-breaker path in a single trace

> As a 🛠️ platform engineer, I want one trace to show an Ollama timeout followed by a Gemini Flash success for a single scored item, so that I can see the whole fallback path, not just the final outcome.

*Delivered by:* `@traced_layer(...)` wraps both whole functions and inline attempts inside `JudgeCircuitBreaker.judge()` (`src/arbiter_l8/observability/decorators.py`)

---

### ✅ 🔭 Export to the same Collector every other Rhizome Risk service uses

> As a 🛠️ platform engineer, I want arbiter-l8's traces and metrics on the same OTLP Collector as Sentinel-L7/Synapse-L4/EventHorizon, so that it's monitored alongside them rather than through a bespoke dashboard.

*Delivered by:* OTLP/HTTP export to `${OTEL_EXPORTER_OTLP_ENDPOINT}`, `OTEL_SERVICE_NAME` defaulting to `arbiter-l8` (`src/arbiter_l8/observability/tracing.py`, `metrics.py`)

---

### ✅ 🔭 See a prompt or model change as a visible step change

> As a 🛠️ platform engineer, I want `run_eval()` to emit precision/recall/F1/accuracy as a gauge on every call, so that a prompt or model swap shows up as a step change in Grafana over time, not just a one-off printed number.

*Delivered by:* `arbiter_l8.harness.metric` gauge, labeled `metric=precision|recall|f1|accuracy`, `label=<label>|overall` (`src/arbiter_l8/observability/metrics.py`)

---

### ✅ 🔭 Confirm telemetry is actually reaching a live Collector

> As a 🛠️ platform engineer, I want arbiter-l8's traces showing up in Tempo like every other Rhizome Risk service, so that I know the instrumentation is really flowing, not just correct in theory.

*Delivered by:* confirmed against a live Collector — real `evaluate_item` traces and `arbiter_l8.judge.outcome`/`arbiter_l8.layer.latency` metrics landing in Tempo/Grafana (`docs/assets/grafana-2026-07-23 162852.png`; README Observability status)

---

### 🔲 🔭 Measure judge trustworthiness, not just judge availability

> As a 🧱 Maintainer, I want a judge/human agreement rate computed once human review exists, so that "% scored by judge" (an uptime signal) stops standing in for "the judge's verdicts are actually correct" (a calibration signal) — two claims that look identical on a dashboard today but aren't.

*TODO:* depends on the human-review story above existing first; `arbiter_l8.judge.outcome` currently answers "did an LLM respond," not "was it right" (`src/arbiter_l8/observability/metrics.py`)

---

**🔲 🛠️ See why a judge attempt failed, not just that it failed**
As a 🛠️ Platform Engineer, I want `exception.type` and `exception.message` surfaced as columns in the Judge Chain Errors panel, so that I can distinguish a model-output failure (non-label verdict) from a network failure (timeout/connect error) without opening each span individually.

*TODO:* `_call_ollama`/`_call_gemini_flash` collapse six distinct failure modes into one `except Exception` branch by design (correct for the circuit breaker); the exception detail exists on the span but isn't in the table view (`src/arbiter_l8/online/judge.py`)

---

## 🔍 Codebase Maintainability

### ✅ 🔍 Keep one taxonomy-agnostic label instead of a shared enum

> As a 🧱 maintainer, I want `label` to stay a plain string, not a shared enum, so that Sentinel's `risk_level` and Synapse's `status` vocabularies never leak into each other through the harness.

*Delivered by:* `EvalPrediction.label: str` (`src/arbiter_l8/models.py`; ADR-0001 Prediction Contract)

---

### ✅ 🔍 Read the judge's prompt from a versioned file, never hardcode it

> As a 🧱 maintainer, I want the judge's prompt loaded from a versioned Markdown+txt pair with a changelog and a "Used by" list, so that a prompt change is reviewable the same way a code change is.

*Delivered by:* `prompts/judge.md` + `prompts/judge.txt`, mirroring Sentinel-L7's own `prompts/*.md`+`*.txt` convention (README Observability/Judge section)

---

### ✅ 🔍 Initialize OpenTelemetry before anything else can race it

> As a 🧱 maintainer, I want the OTel SDK initialized as an import-time side effect, so that arbiter-l8 doesn't reproduce Synapse-L4's suspected trace-fragmentation bug, caused by configuring OTel inside a FastAPI lifespan handler after routes already exist.

*Delivered by:* `observability/tracing.py`/`metrics.py` initialize at import time, with the reasoning documented in the module docstring (README Observability)

---

### ✅ 🔍 Never let a real external call slip into the automated suite

> As a 🧱 maintainer, I want every external HTTP call mocked at the boundary in tests, so that `uv run pytest` never depends on a live Sentinel-L7, Synapse-L4, Ollama, or Upstash being reachable.

*Delivered by:* `pytest` + `respx` mocking every external call at the HTTP boundary (README Stack/Testing)

---

### 🚫 🔍 Fix Synapse-L4's own extraction bug from inside arbiter-l8

> As a 🧱 maintainer, I want to patch Synapse-L4's self-contradictory fast-path extraction directly, since arbiter-l8 is what found the bug.

*Deferred:* it's Synapse-L4's own code; out of scope to fix here per ADR-0001's standalone boundary — tracked only as a documented Known Issue (README Known Issues)

---

See also: [README.md](../README.md) · [docs/adr/0001-standalone-module.md](adr/0001-standalone-module.md) · [docs/adr/0002-online-escalation-pipeline.md](adr/0002-online-escalation-pipeline.md) · [docs/DEV_GETTING_STARTED.md](DEV_GETTING_STARTED.md).