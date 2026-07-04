# ADR 0001 — Build sentinel-eval as a Standalone Module, Not Embedded in Sentinel-L7

**Status:** Accepted
**Date:** 2026-07-03

---

## Context

Sentinel-L7's `TransactionProcessorService` and Synapse-L4's
`AxiomProcessorService` both produce AI-justified outputs (semantic-cache
verdicts, Gemini Flash + RAG extractions), but neither system has a way to
systematically measure whether those outputs are *correct* — only whether
they're *structurally valid* (Axiom contract enforcement via
Pydantic/Instructor is validation, not quality scoring).

Two systems now produce this class of output. That's the concrete
downstream trigger — per this suite's "wait until it hurts" ADR
philosophy — for treating evaluation as its own layer rather than
deferring the abstraction further.

Two paths were considered:

1. Embed eval logic inside `sentinel-l7`, calling `ComplianceDriver`
   directly.
2. Build `sentinel-eval` as a separate module/repo with a
   system-under-test interface, scoring Sentinel-L7 and Synapse-L4 (and
   future services) without being deployed alongside either.

---

## Decision

Build `sentinel-eval` as a standalone module with a defined interface:

```python
def run_eval(system_under_test: Callable, dataset: EvalDataset) -> EvalReport:
    ...
```

`system_under_test` wraps whatever service is being scored (initially
Sentinel-L7's `ComplianceDriver`, later Synapse-L4's Axiom pipeline) behind
a common call signature, so the harness itself has no Sentinel-specific or
Synapse-specific code in it.

### Prediction contract

`ComplianceDriver::analyze()` and Synapse-L4's `Axiom`/`AxiomDraft` return
different domain shapes (compliance verdict vs. telemetry extraction), so
the callable can't return an unconstrained structure — the harness needs a
normalized prediction envelope, not raw domain output, to score
generically:

```python
class EvalPrediction(BaseModel):
    id: str                        # source_id / correlation token
    raw_output: dict[str, Any]     # untouched domain payload, for debugging
    label: str                     # normalized outcome, e.g. Sentinel's
                                    # risk_level (low|medium|high|critical|
                                    # unknown) or Synapse's status
                                    # (nominal|degraded|critical)
    confidence: float
    metadata: dict[str, Any] = {}  # latency, provider used, token usage
```

`label` is intentionally a plain string, not a shared Literal enum —
Sentinel's `risk_level` and Synapse's `status` are different taxonomies
with different values, and forcing them into one enum would leak one
service's domain vocabulary into the harness. Each system-under-test
wrapper is responsible for mapping its own domain output into `label`; the
harness only ever compares `label` against ground truth for whichever
system it's currently scoring.

### Offline / online split

Reframes the existing Option A vs. B ground-truth decision as the split
itself, rather than a single flag serving two purposes:

- **Offline (Option A — ground truth):** `TransactionSeeder`-generated
  labeled corpus. Run through the system-under-test, score against
  `is_threat` directly. Precision/recall/F1 over time as prompts/models
  change. No judge model required — this path is unaffected by LLM
  availability entirely.
- **Online (Option B — realistic, unlabeled):** sampled production
  traffic, no ground truth available. Scored via a layered, cost-ordered
  pipeline:
  1. Rule-based heuristics (confidence thresholds, field-contradiction
     checks) — free, deterministic, always available.
  2. Cross-provider disagreement (Gemini vs. OpenRouter via the existing
     dual-provider `ComplianceDriver`, or same-provider temperature
     variance) — reuses infrastructure already built, no new cost.
  3. Embedding-based consistency (Upstash Vector) — flags verdicts that
     diverge from near-identical historical embeddings.
  4. LLM-as-judge (remote Ollama over Tailscale, partner's host —
     separate from the `nomic-embed-text` embedding host used for the
     driver migration), reserved for the ambiguous tail flagged by layers
     1–3, not run on every transaction.

  Note: this eval judge is distinct from the stubbed
  `synapse-l4-judge.md` prompt already in Sentinel-L7's `prompts/`
  directory, which scores `anomaly_score` for routing Axioms to AI audit
  in production — different purpose, different consumer, not yet
  implemented. Worth keeping these two "judge" concepts named distinctly
  in docs so they don't get conflated.

### Judge availability as a first-class failure mode

The remote Ollama judge is *not* a required dependency. It sits behind a
circuit breaker with the same shape as Sentinel's existing
external-provider handling:

- Try Ollama (free, but uptime not guaranteed — partner-owned remote
  host).
- On failure/timeout, fall back to Gemini Flash free tier.
- On failure/timeout there too, fall back to heuristics-only scoring for
  that batch.
- Judge availability is logged as its own metric (`% ambiguous
  transactions scored by judge vs. fallback`), not hidden inside the eval
  output — this is itself a useful signal about real operating
  conditions, not a gap to paper over.

No paid LLM tier is assumed anywhere in this design. Gemini Flash's free
tier is a secondary fallback behind Ollama, ahead of heuristics-only, if
Ollama is unreachable — same circuit-breaker chain, just deeper.

### Embedding dimension consistency

Layer 3 (embedding-based consistency) must call through the same embedding
path Sentinel-L7 uses, not maintain its own. This matters concretely right
now: Sentinel-L7 is mid-migration from Gemini embeddings to
`nomic-embed-text:v1.5` (768-dim, per
`docs/adr/0025-ollama-local-embedding-provider.md` in sentinel-l7). If
`sentinel-eval` embeds independently against a different model or
dimension, Upstash Vector will reject writes/queries on dimension mismatch
the moment the two diverge. `sentinel-eval` should call Sentinel-L7's
embedding driver (or read its config) rather than hardcoding a model name.

---

## Alternatives Considered

**Embed in Sentinel-L7.** Rejected. Would couple eval-run failures to
Sentinel's deploy/dependency surface, and would hard-code the eval
interface to `ComplianceDriver` specifically — precluding Synapse-L4 (or
any future service) from being scored without duplicating the harness.
Also weaker as a standalone portfolio artifact: an interviewer evaluating
"did you build an eval framework" shouldn't have to read a compliance
engine to find it.

**LLM-as-judge as the default/required layer.** Rejected. Both available
LLM sources (partner's remote Ollama, Flash free-tier credits) are
unreliable by construction — neither is a service with an uptime
guarantee. Making the judge required would make the entire online-eval
path fail closed whenever either dependency is down. Deterministic and
infrastructure-reuse layers (heuristics, cross-provider disagreement,
embedding consistency) are ordered first specifically because they have no
external dependency at all.

**Judge model trusted without validation.** Rejected implicitly by
design — before the Ollama judge is used to score unlabeled traffic, its
verdicts should be validated against the labeled `TransactionSeeder` set
first (same harness, offline path). A judge that hasn't been evaluated
against ground truth isn't yet trustworthy to evaluate anything else.

> **Validated 2026-07-04** (Phase 3 step 8): live 25-example sample against
> the real Ollama judge and a real Sentinel-L7 server, scored against the
> `sentinel:export-ground-truth` fixture — 92% binary agreement (threat vs.
> not), matching Sentinel-L7's own accuracy on the same sample. Full
> results and methodology in
> `docs/journal/sentinel-eval-2026-07-04T1720-ground-truth-export-and-judge-validation.md`.
> A prompt-following gap was found (occasional non-taxonomy verdict tokens)
> and is tracked there as a follow-up, not a blocker to this gate.

---

## Consequences

**Positive:**
- `sentinel-eval` becomes a citable, standalone artifact independent of
  Sentinel-L7's repo.
- Offline eval runs are fully decoupled from LLM availability — the
  harness's core signal (precision/recall on labeled data) works even if
  both Ollama and Flash are down.
- Online eval quality degrades gracefully rather than failing outright
  when the judge is unavailable, at the cost of coarser signal on the
  ambiguous tail during outages.

**Negative / Trade-offs:**
- Adds a new repo/module to maintain and version against Sentinel-L7 and
  Synapse-L4's evolving interfaces — acceptable given both already expose
  stable-enough contracts (`ComplianceDriver`, Axiom schema).
- Defers (not solves) the harder question of *what ground truth looks
  like for Synapse-L4's Axiom extraction* specifically, since
  `TransactionSeeder` currently only labels Sentinel-side threat
  detection. Flagged as follow-up scope, not blocking this ADR.
