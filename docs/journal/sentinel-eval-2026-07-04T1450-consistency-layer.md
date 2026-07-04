---
id: sentinel-eval-2026-07-04T1450-consistency-layer
repo: sentinel-eval
title: "Embedding Consistency Layer: the First Genuinely Live-Verified Piece"
date: 2026-07-04
phase: 3
tags: [additive-observability, live-verification, secret-handling]
files: [src/sentinel_eval/config.py, src/sentinel_eval/online/consistency.py, tests/test_config.py, tests/test_consistency.py, tests/test_disagreement_stub.py, README.md]
---

Implemented layer 3 for real: `make_ollama_embed_fn()` mirrors Sentinel-L7's
`OllamaEmbeddingDriver::embed()` exactly (verified against that file, not
assumed — `POST {OLLAMA_URL}/api/embeddings`, `{"model", "prompt": "{task}:
{text}"}`, response `{"embedding": [...]}`), and `query_upstash_vector()`
mirrors `VectorCacheService::searchNamespace()` exactly. Unlike the two
adapter steps, this one got a genuine live round-trip: real 768-dim
embedding from the actual Tailscale Ollama host, real query against the
live Upstash Vector index, both succeeding.

### Decision: search_query task prefix, not search_document

`make_ollama_embed_fn()` defaults to `"search_query"` rather than
`"search_document"` — this layer only ever embeds a prediction's narrative
to query against already-indexed historical content; it never indexes new
content itself, so the document-side prefix would be a category error, not
just a suboptimal choice.

### Challenge: two "similar-looking" hosts turned out to be one, and one secret turned out to be mistyped twice

Two separate corrections during this step, both worth recording as a
pattern rather than one-off errors:

1. Assumed `OLLAMA_URL` (embedding) and `OLLAMA_JUDGE_HOST` (judge) must be
   different machines because the ADR frames them as separate roles.
   Confirmed directly with the user: in this environment they're the same
   Tailscale host (`100.82.223.70`) serving both models. Fixed the module
   docstring and a test comment that had overclaimed "different machines"
   as a hard fact rather than "different settings that happen to collide
   here."
2. The Upstash Vector token failed auth twice — not because the token was
   wrong, but because retyping a ~90-character base64 secret across chat
   messages introduced a transcription error each time (a dropped `=`, then
   a different substring mismatch). Diagnosed by fetching Upstash's actual
   error body (`"Unauthorized: invalid name or password"`) instead of just
   the bare 403, which made clear this was an auth problem worth asking the
   user to re-paste for, not a namespace/permissions issue worth debugging
   further on the code side.

### Decision: verify "zero matches" is correct, not silently accept it

A live query against the real Upstash index returned 0 matches. Rather
than treating that as "the call worked, ship it," fetched the index's own
`/info` endpoint and confirmed the `transactions` namespace has zero
vectors in it currently (only `""` and `policies` have data) — so zero
matches was the *correct* answer for this dev environment, not a silent
bug. Matches the "verify a status claim against the artifact" pattern
already established in rhizome-observability's own journal.

### Challenge: consistency.py was no longer a stub, so its stub test was stale

`tests/test_online_stubs.py` asserted both `disagreement.py` and
`consistency.py` raise `NotImplementedError`. Once `consistency.py` got a
real implementation, that assertion became false for half the file. Split
it: `test_disagreement_stub.py` keeps the still-accurate half,
`test_consistency.py` covers the new real behavior. Renaming/splitting the
test file when a stub graduates to a real implementation, rather than
leaving a half-stale file with a now-misleading name, is the same
discipline as updating a docstring that no longer matches the code.
