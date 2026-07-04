"""Layer 3: embedding-based consistency.

Flags verdicts that diverge from the label distribution of near-identical
historical embeddings in Sentinel-L7's Upstash Vector semantic cache
(namespace `transactions` — verified against
`TransactionProcessorService::NAMESPACE` directly, not the looser "ns:
default" wording in an earlier draft of the ADR).

IMPORTANT (see docs/adr/0001-standalone-module.md, "Embedding dimension
consistency"): this module must never hardcode an embedding model or
dimension independently. `make_ollama_embed_fn()` calls the exact same
local Ollama host/model/task-prefix convention as Sentinel-L7's own
`OllamaEmbeddingDriver::embed()` (verified against that file directly:
`POST {OLLAMA_URL}/api/embeddings`, body `{"model", "prompt": "{task}:
{text}"}`, response `{"embedding": [...]}`) — so the vector this module
produces always matches whatever dimension/model Sentinel-L7 is currently
writing to. Sentinel-L7 is no longer "mid-migration" (an earlier draft of
this module's docstring said that); its live config has
`SENTINEL_EMBEDDING_DRIVER=ollama` as the active default.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from sentinel_eval import config
from sentinel_eval.models import EvalPrediction
from sentinel_eval.observability import traced_layer

# Must be backed by the system-under-test's own embedding driver/config —
# e.g. make_ollama_embed_fn() below, calling Sentinel-L7's exact Ollama
# host/model — never a dimension/model chosen independently here.
EmbeddingFn = Callable[[str], list[float]]

_TASK_QUERY = "search_query"


def make_ollama_embed_fn(
    *,
    task: str = _TASK_QUERY,
    client: httpx.Client | None = None,
    timeout: float = 10.0,
) -> EmbeddingFn:
    """Build the real embed_fn — calls Sentinel-L7's local Ollama directly.

    Defaults to the "search_query" task prefix, not "search_document":
    this layer only ever embeds a prediction's narrative to *query* against
    already-indexed historical content — it never indexes new content
    itself, so it should never use the document-side prefix.
    """
    http_client = client or httpx.Client(timeout=timeout)

    def embed(text: str) -> list[float]:
        response = http_client.post(
            f"{config.ollama_embedding_host()}/api/embeddings",
            json={"model": config.ollama_embedding_model(), "prompt": f"{task}: {text}"},
        )
        response.raise_for_status()
        return response.json()["embedding"]

    return embed


@dataclass
class UpstashVectorMatch:
    id: str | None
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


class UpstashVectorError(RuntimeError):
    """Raised when Upstash Vector credentials are missing or the query fails."""


def query_upstash_vector(
    vector: list[float],
    *,
    namespace: str | None = None,
    top_k: int = 5,
    threshold: float | None = None,
    client: httpx.Client | None = None,
    timeout: float = 5.0,
) -> list[UpstashVectorMatch]:
    """Query Sentinel-L7's Upstash Vector index for near-identical historical
    embeddings, mirroring VectorCacheService::searchNamespace() exactly
    (same endpoint shape, same includeMetadata request, same score-filtering
    behavior — results below threshold are dropped, matching that method's
    own `>= $threshold` filter).
    """
    url = config.upstash_vector_url()
    token = config.upstash_vector_token()
    if not url or not token:
        raise UpstashVectorError(
            "UPSTASH_VECTOR_REST_URL/UPSTASH_VECTOR_REST_TOKEN are not set"
        )

    resolved_namespace = namespace or config.upstash_vector_transactions_namespace()
    resolved_threshold = (
        threshold if threshold is not None else config.upstash_vector_similarity_threshold()
    )

    http_client = client or httpx.Client(timeout=timeout)
    response = http_client.post(
        f"{url}/query/{resolved_namespace}",
        json={"vector": vector, "topK": top_k, "includeMetadata": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.status_code >= 400:
        raise UpstashVectorError(f"Upstash Vector query failed ({response.status_code})")

    results = response.json().get("result") or []
    return [
        UpstashVectorMatch(id=r.get("id"), score=r.get("score", 0.0), metadata=r.get("metadata", {}))
        for r in results
        if r.get("score", 0.0) >= resolved_threshold
    ]


@dataclass
class ConsistencyResult:
    prediction_id: str
    neighbor_labels: list[str]
    neighbor_similarities: list[float]
    consistent: bool


@traced_layer("embedding_consistency")
def score_consistency(
    prediction: EvalPrediction,
    text: str,
    embed_fn: EmbeddingFn,
    *,
    top_k: int = 5,
) -> ConsistencyResult:
    """Embed `text`, query the vector store for nearest historical neighbors,
    and check whether `prediction.label` agrees with their label distribution.

    A prediction with no neighbors above the similarity threshold is
    treated as consistent by default — there's no historical evidence to
    flag it as diverging from. `neighbor_labels` reads each match's cached
    `analysis.risk_level` (the same field TransactionProcessorService's own
    cache-hit path reads, widened in the Sentinel-L7 adapter's paired
    change to include risk_level alongside the boolean is_threat).
    """
    vector = embed_fn(text)
    matches = query_upstash_vector(vector, top_k=top_k)

    neighbor_labels = [
        label
        for m in matches
        if (label := m.metadata.get("analysis", {}).get("risk_level")) is not None
    ]
    neighbor_similarities = [m.score for m in matches]

    if not neighbor_labels:
        consistent = True
    else:
        most_common_label, _ = Counter(neighbor_labels).most_common(1)[0]
        consistent = prediction.label == most_common_label

    return ConsistencyResult(
        prediction_id=prediction.id,
        neighbor_labels=neighbor_labels,
        neighbor_similarities=neighbor_similarities,
        consistent=consistent,
    )
