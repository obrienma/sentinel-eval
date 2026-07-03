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

1. Write a callable `(input: dict) -> EvalPrediction` that calls the target
   service and maps its domain output into the prediction contract above.
   Put the untouched domain payload in `raw_output` and a normalized
   outcome string in `label`.
2. For offline scoring: build an `EvalDataset` (see
   `tests/fixtures/compliance_dataset.json` for the shape) and call
   `run_eval(your_callable, dataset)`.
3. For online scoring: run `online.heuristics.run_heuristics()` on each
   prediction first; only escalate to disagreement/consistency/judge layers
   for predictions it flags. (Layers 2–4 are scaffolded interfaces today,
   not wired into a single pipeline function yet.)

## Development

```bash
uv sync                 # install dependencies
uv run pytest           # run the test suite
```
