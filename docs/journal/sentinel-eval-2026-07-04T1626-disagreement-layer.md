---
id: sentinel-eval-2026-07-04T1626-disagreement-layer
repo: sentinel-eval
title: "Cross-Provider Disagreement (Layer 2): Real External Failures as the Verification"
date: 2026-07-04
phase: 3
tags: [circuit-breaker, live-verification, error-surfacing]
files: [src/sentinel_eval/online/disagreement.py, src/sentinel_eval/adapters/sentinel_l7.py, tests/test_disagreement.py, tests/test_sentinel_l7_adapter.py, README.md]
---

### Pattern: A Failed Provider Forces Disagreement, Never Gets Excluded

`score_disagreement()` calls every named provider with the same input and
compares labels. A provider call that raises is captured in
`errors_by_provider` (`str(exception)`) rather than dropped from the
comparison silently. `agreed` is only `True` when there are zero errors and
every successful provider returned the exact same label — an errored
provider makes agreement unknowable, not automatically true, so it forces
`agreed=False` rather than being quietly excluded and letting the remaining
providers "agree" on their own.

### Pattern: Driver Override as a Factory Parameter, Not a Call-Time Argument

`adapters.sentinel_l7.make_sentinel_l7_system_under_test()` gained a
`driver` parameter (`'gemini'`/`'openrouter'`/`'ollama'`) used to build one
`SystemUnderTest` callable per provider — `score_disagreement` is handed a
`dict[str, ProviderCall]` of these pre-built callables, so the disagreement
layer itself stays domain-agnostic (it never constructs adapters or knows
about MCP/HTTP) and only ever calls each one with the same `input_data`.

### Challenge: None on the Implementation Side — the Real Challenge Was External

The implementation itself was straightforward once step 6 (the sentinel-l7
driver override) existed to build on. The interesting part came from live
verification: a real round trip against a temporarily-started local
Sentinel-L7 server (`php artisan serve`, stopped again after) showed Ollama
answering correctly, but both OpenRouter and Gemini genuinely failing —
OpenRouter's configured free model (`meta-llama/llama-3.3-8b-instruct:free`)
has been retired upstream (`404: "No endpoints found"`), and Gemini hit the
same free-tier quota exhaustion already seen validating the judge layer in
the previous phase. Neither is a bug in this code; both are pre-existing
external/environment drift in sentinel-l7's `.env`, out of scope for this
step to fix.

### Decision: Treat the Real Failures as the Verification, Not a Blocker

Rather than chasing a fully-successful two-provider comparison (which would
require either a fresh OpenRouter free model or waiting out Gemini's quota
window — neither in this session's control), treated the real errors as a
more informative live-verification outcome than an all-success run would
have been: they exercised `errors_by_provider`'s exact purpose — surfacing
a genuine external failure rather than swallowing it or crashing the
comparison — against real APIs, not mocks. `agreed=False` and
`confidence_spread=0.0` were both confirmed correct for the single-successful-
provider case in each live run.

### Decision: Replaced the Stub Test File, Not Left It Alongside

`tests/test_disagreement_stub.py` asserted `NotImplementedError` — stale the
moment `disagreement.py` became real, same as `consistency.py`'s stub test
in the previous phase. Deleted it and added `tests/test_disagreement.py`
with real coverage (agreement, disagreement, one provider erroring, all
providers erroring, missing-id UUID generation) rather than leaving a
half-stale file with a misleading name.
