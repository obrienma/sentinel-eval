---
type: cloze
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, error-surfacing]
---
In `score_disagreement()`, a provider whose call raises is recorded in
{{c1::errors_by_provider}} rather than dropped from the comparison, and
`agreed` is forced to `False` whenever any provider errored — an error
makes agreement unknowable, not automatically true.

Extra: sentinel-eval · Pattern: A Failed Provider Forces Disagreement, Never Gets Excluded
See: docs/journal/sentinel-eval-2026-07-04T1626-disagreement-layer.md

---
type: basic
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, error-surfacing, decision]
---
Q: Why does a provider that raises during `score_disagreement()` force
`agreed=False`, rather than being excluded from the comparison so the
remaining providers can still "agree" with each other?

A: An errored provider means we genuinely don't know what it would have
said — treating the remaining providers' agreement as meaningful would
silently assume the failed provider would have agreed too, which is not a
safe assumption. Forcing `agreed=False` whenever any provider errored keeps
"agreed" meaning "every provider that was asked actually answered the same
way," not "the providers that happened to succeed agreed."

Extra: sentinel-eval · Pattern: A Failed Provider Forces Disagreement, Never Gets Excluded
See: docs/journal/sentinel-eval-2026-07-04T1626-disagreement-layer.md

---
type: basic
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, live-verification, fixture-defect]
---
Q: A live round-trip against a real local Sentinel-L7 server showed
OpenRouter and Gemini both failing (a real 404 and a real 429,
respectively) while only Ollama succeeded. Why was this treated as a
successful verification rather than a blocker?

A: Both failures were genuine external/environment issues outside this
step's control — OpenRouter's configured free model had been retired
upstream, and Gemini had hit the same free-tier quota exhaustion already
seen validating the judge layer. Rather than chasing a clean two-success
comparison (which nothing in this session could force), the real failures
exercised exactly what `errors_by_provider` exists to do: surface a genuine
external failure instead of swallowing it or crashing the comparison —
arguably stronger evidence the error path works than an all-success run
would have been.

Extra: sentinel-eval · Decision: Treat the Real Failures as the Verification, Not a Blocker
See: docs/journal/sentinel-eval-2026-07-04T1626-disagreement-layer.md

---
type: cloze
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, adapter-pattern]
---
`make_sentinel_l7_system_under_test()` takes a `driver` parameter used to
build one callable per provider at {{c1::factory}} time (not call time) —
`score_disagreement` is just handed a `dict[str, ProviderCall]` of these
pre-built callables, keeping the disagreement layer itself domain-agnostic.

Extra: sentinel-eval · Pattern: Driver Override as a Factory Parameter, Not a Call-Time Argument
See: docs/journal/sentinel-eval-2026-07-04T1626-disagreement-layer.md

---
type: basic
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, test-maintenance]
---
Q: Why was `tests/test_disagreement_stub.py` deleted rather than kept
alongside the new `tests/test_disagreement.py`?

A: It asserted `score_disagreement()` raises `NotImplementedError` — true
only while the module was a stub. Once `disagreement.py` had a real
implementation, that assertion became false, so the file would either fail
or (worse) silently test nothing meaningful. Same discipline already
applied to `consistency.py`'s stub test in the previous phase: delete the
stale stub test and replace it with real coverage rather than leaving a
half-stale file with a misleading name.

Extra: sentinel-eval · Decision: Replaced the Stub Test File, Not Left It Alongside
See: docs/journal/sentinel-eval-2026-07-04T1626-disagreement-layer.md
