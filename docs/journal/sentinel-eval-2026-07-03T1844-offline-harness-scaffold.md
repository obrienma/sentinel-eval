---
id: sentinel-eval-2026-07-03T1844-offline-harness-scaffold
repo: sentinel-eval
title: "Offline Eval Harness Scaffold + Online Layer Stubs"
date: 2026-07-03
phase: 1
tags: [adapter-pattern, circuit-breaker, leaky-abstraction, fail-loud, confusion-matrix, pydantic, uv, pytest]
files: [pyproject.toml, src/sentinel_eval/models.py, src/sentinel_eval/harness.py, src/sentinel_eval/online/heuristics.py, src/sentinel_eval/online/disagreement.py, src/sentinel_eval/online/consistency.py, src/sentinel_eval/online/judge.py, tests/fixtures/compliance_dataset.json, tests/test_harness.py, README.md, docs/adr/0001-standalone-module.md]
---

### Pattern: Adapter

`EvalPrediction` is an adapter target, not a shared domain model. Sentinel-L7's
`ComplianceDriver::analyze()` and Synapse-L4's `Axiom` pipeline each speak a
different bounded-context vocabulary (`risk_level` vs. `status`). Rather than
building the harness against either vocabulary, each system-under-test
callable adapts its own domain output into the common `EvalPrediction`
envelope at the boundary; `run_eval()` never sees a domain-specific shape.

### Pattern: Circuit Breaker

`online/judge.py`'s `JudgeCircuitBreaker` implements the same shape as
Sentinel's existing external-provider handling: try Ollama, catch failure,
try Gemini Flash, catch failure, fall back to heuristics-only — with the
fallback outcome itself recorded as a first-class metric
(`JudgeMetrics.pct_scored_by_judge`) rather than swallowed.

### Anti-Pattern Avoided: Leaky Abstraction (shared enum across bounded contexts)

`EvalPrediction.label` is a plain `str`, not a `Literal` enum spanning both
`risk_level` and `status`. A shared enum would force one service's
vocabulary to leak into the other's scoring path the moment their taxonomies
diverge further (e.g. Sentinel adds a label Synapse has no equivalent for).
Keeping `label` untyped at the harness boundary means each adapter owns its
own vocabulary completely.

### Anti-Pattern Avoided: Fail-Silent Stub Masking as Real Fallback

In `JudgeCircuitBreaker.judge()`, `NotImplementedError` from the stubbed
`_call_ollama`/`_call_gemini_flash` is re-raised rather than caught by the
generic `except Exception` fallback path. Without this, calling `judge()`
today would silently record every verdict as `heuristics_fallback` —
indistinguishable from a real Ollama/Flash outage. Failing loudly on "not
built yet" keeps that failure mode legible until the TODOs are filled in.

### Challenge: A perfect-predictor test can't validate precision/recall math

The first test written (`perfect_sut`, 100% accuracy) passed even before the
per-label precision/recall/F1 formulas in `harness.py` were fully correct,
because when every prediction is correct, precision/recall/F1 all trivially
collapse to 1.0 regardless of how the confusion-matrix counts are wired up.
Had to add a second test with a deliberately flawed predictor (mislabeling
every `critical` example as `high`) and hand-compute the expected
precision/recall for both affected labels to actually exercise the
off-diagonal confusion-matrix logic.

### Decision: heuristics-only implemented; disagreement/consistency/judge raise NotImplementedError

Rather than stubbing the three unbuilt online layers with pass-through
no-ops (e.g. returning an empty/neutral result), they raise
`NotImplementedError` with a docstring TODO. Tradeoff: this means the online
pipeline can't be run end-to-end yet even for a smoke test — accepted
because a silently-neutral stub is worse: it would look like "layer ran and
found nothing" rather than "layer doesn't exist yet."
