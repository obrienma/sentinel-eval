"""Layer 3: embedding-based consistency — not yet implemented.

Flags verdicts that diverge from the label distribution of near-identical
historical embeddings in Upstash Vector.

IMPORTANT (see docs/adr/0001-standalone-module.md, "Embedding dimension
consistency"): this module must never hardcode an embedding model or
dimension. Sentinel-L7 is mid-migration from Gemini embeddings (1536-dim)
to `nomic-embed-text:v1.5` (768-dim) — see sentinel-l7's
docs/adr/0025-ollama-local-embedding-provider.md. Embedding independently
here against a different model/dimension will cause Upstash Vector
dimension-mismatch errors the moment the two diverge. Callers must inject
an `embed_fn` that calls through Sentinel-L7's EmbeddingService/driver (or
reads its config), not a locally-chosen model.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sentinel_eval.models import EvalPrediction

# Must be backed by the system-under-test's own embedding driver/config —
# e.g. a thin wrapper calling Sentinel-L7's App\Services\EmbeddingService
# (via HTTP/CLI bridge) — never a dimension/model chosen independently here.
EmbeddingFn = Callable[[str], list[float]]


@dataclass
class ConsistencyResult:
    prediction_id: str
    neighbor_labels: list[str]
    neighbor_similarities: list[float]
    consistent: bool


def score_consistency(
    prediction: EvalPrediction,
    text: str,
    embed_fn: EmbeddingFn,
    *,
    top_k: int = 5,
) -> ConsistencyResult:
    """Embed `text`, query the vector store for nearest historical neighbors,
    and check whether `prediction.label` agrees with their label distribution.

    TODO:
      1. `vector = embed_fn(text)` — embed_fn must be injected by the caller
         from Sentinel-L7's embedding driver/config, so dimension always
         matches whatever index Sentinel-L7 is currently writing to.
      2. Query Upstash Vector (ns: "default" or "policies", per caller) for
         `top_k` nearest neighbors to `vector`.
      3. Compare `prediction.label` against the neighbors' stored labels.
      4. Populate and return a ConsistencyResult.
    """
    raise NotImplementedError("consistency scoring is scaffolded, not implemented")
