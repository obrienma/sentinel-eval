---
id: sentinel-eval-2026-07-04T1720-ground-truth-export-and-judge-validation
repo: sentinel-eval
title: "Ground-Truth Export and the Deferred Judge-Validation Gate, Closed"
date: 2026-07-04
phase: 3
tags: [ground-truth, live-verification, judge, fixture-defect, semantic-cache]
files: [tests/fixtures/sentinel_l7_ground_truth.json, README.md]
cross_ref: observability
cross_ref_id: sentinel-eval-2026-07-04T1720-ground-truth-export-and-judge-validation
---

Step 5 deferred the ADR-0001-required judge-validation gate (run the real
judge against a labeled fixture, check agreement, before trusting it
online) because the only fixture available (`compliance_dataset.json`) had
Synapse-shaped `raw_output` paired with Sentinel-shaped `expected_label` —
a pre-existing mismatch invisible to `run_eval()`'s label-only comparison
until the judge actually reasoned over the raw fields, producing a
nonsensical 6.7% accuracy. This step closes that gate using the new
taxonomy-consistent fixture from Sentinel-L7's `sentinel:export-ground-truth`
command (`docs/journal.md#phase-18` in that repo).

### Pattern: Force the Driver Override to Get an Independent Answer, Not a Stale Cache Hit
The first live validation attempt returned `source: cache_hit` and
`risk_level: 'low'` for every single one of 25 sampled transactions,
including ones ground-truth-labeled `high` — a 52% accuracy that looked like
a judge/model failure but wasn't. Sentinel-L7's semantic vector cache
(similarity threshold 0.95) matches on embedding similarity, not identity;
the "suspicious" merchant profile (`RapidRemit Structuring Node`) generates
transactions narrow enough in amount range and message wording that they
embed near-identically to each other, so the *first* one ever analyzed
(against the app-wide default driver) got cached as `low` and every
subsequent similar transaction inherited that stale, individually-cached-
wrong verdict — a real cache-amplification effect, not a bug in this
validation. Re-running with the adapter's `driver='ollama'` override (Phase
3 step 6/7's per-request bypass) got a fresh, uncached answer per
transaction and immediately produced sane, varied verdicts.

### Decision: Binary-Collapse the Scoring, Not Just the Export
Even with fresh answers, strict string equality between Sentinel-L7's
graded `risk_level` (`low`/`medium`/`high`/`critical`) and the fixture's
binary `expected_label` (`'high'`/`'low'`) under-counts correct threat
catches — a `critical` verdict on a real threat is right, not wrong. Scored
both ways: strict accuracy (84% Sentinel-L7 / 80% judge) and binary
accuracy collapsing `medium`/`high`/`critical` to `'high'` (92% both) — the
binary number is the one that actually reflects what the ground truth can
justify claiming, and it should be the one trusted going forward for this
fixture specifically.

### Decision: Call the Judge Unconditionally for This Validation, Bypassing the Heuristic Gate
`evaluate_item()`'s normal path only escalates to the judge when
`run_heuristics()` flags a prediction — and in this sample, Sentinel-L7's
Ollama-driver confidence was uniformly high (0.85-0.98), so the heuristic
gate never fired and the judge would never have run at all through the
normal path. Since the point of this pass was specifically to validate the
*judge's* agreement rate (not the gated online pipeline's), the validation
script called `JudgeCircuitBreaker.judge()` directly on every prediction
instead of going through `evaluate_item()`'s gate. This is a validation-only
deviation from production behavior, not a change to `evaluate_item()`
itself.

### Challenge: The Judge Sometimes Returns a Non-Taxonomy Token Instead of a Label
Two of 25 live verdicts were not valid labels at all: `"reject"` and
`"correct"` — the model echoing back an evaluative word instead of
restating a `risk_level` value, despite the prompt asking for "the label
you believe is correct." Both were counted as wrong under strict
comparison (correctly — they're not the ground-truth label) but happened to
land on the *correct side* of the binary collapse in one case (`"correct"`
paired with an actually-correct-suspicion transaction) by coincidence, not
by the model actually stating an interpretable verdict. This is a genuine
prompt-following gap worth a future `prompts/judge.txt` revision (e.g.
constraining the `verdict` field to an explicit enum in the request) —
not fixed in this step, since the 25-example live sample was scoped as a
validation pass, not a prompt-iteration pass.

### Decision: 25-Example Live Sample, Not the Full 200
Each Ollama judge call takes ~12s; the full 200-row fixture would be
~40+ minutes of live calls for marginal additional confidence at this
stage. Sampled all 10 `high`-labeled rows (the rarer, more informative
class — the full fixture is only 5% threats by construction, matching the
merchant weight distribution) plus 15 random `low` rows, deterministically
seeded (`random.seed(42)`) so the sample is reproducible if re-run. Confirmed
with the user before running rather than assuming the full-scale run was
worth the wall-clock cost.
