---
type: cloze
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, live-verification]
---
`make_ollama_embed_fn()` defaults to the {{c1::search_query}} task prefix,
not `search_document`, because this layer only ever embeds a prediction's
narrative to query against already-indexed content — it never indexes
new content itself.

Extra: sentinel-eval · Decision: search_query task prefix, not search_document
See: docs/journal/sentinel-eval-2026-07-04T1450-consistency-layer.md

---
type: basic
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, live-verification]
---
Q: A live Upstash Vector query against the real index returned 0 matches.
How was this confirmed to be the correct answer rather than a silent bug?

A: Fetched the index's own `/info` endpoint, which reports vector counts
per namespace. It showed the `transactions` namespace had zero vectors in
this dev environment (only the `""` and `policies` namespaces had data) —
so an empty result was mechanically confirmed correct, not just assumed
because the HTTP call itself didn't error.

Extra: sentinel-eval · Decision: verify "zero matches" is correct, not silently accept it
See: docs/journal/sentinel-eval-2026-07-04T1450-consistency-layer.md

---
type: cloze
deck: Rhizome::sentinel-eval
tags: [sentinel-eval, secret-handling]
---
A 403 from Upstash Vector was diagnosed by fetching the actual response
{{c1::body}} (`"Unauthorized: invalid name or password"`) rather than
stopping at the bare status code — this made clear the token itself was
wrong (a transcription error retyping it across chat), not a
namespace/permissions problem worth debugging in the query code.

Extra: sentinel-eval · Challenge: two "similar-looking" hosts turned out to be one, and one secret turned out to be mistyped twice
See: docs/journal/sentinel-eval-2026-07-04T1450-consistency-layer.md
