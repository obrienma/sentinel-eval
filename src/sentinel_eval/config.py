"""Config for calling out to real system-under-test services.

Same env-var-with-default pattern as observability/_env.py — deliberately
not pydantic-settings, to keep one config style across the codebase rather
than introducing a second one for this narrower need.

OLLAMA_JUDGE_* and OLLAMA_URL/OLLAMA_EMBEDDING_MODEL are independent
settings on purpose, even though in this environment they currently
resolve to the same Tailscale host (100.82.223.70) — one Ollama instance
happens to serve both the judge model (qwen3.5) and the embedding model
(nomic-embed-text) here. The settings stay separate because the *roles*
are distinct (LLM-as-judge vs. Sentinel-L7's embedding driver, see
docs/adr/0001-standalone-module.md "Embedding dimension consistency") and
nothing guarantees they'll always be co-located — conflating them into one
setting would break the moment Sentinel-L7's embedding host and the
judge's host diverge onto separate machines.

OLLAMA_URL and OLLAMA_EMBEDDING_MODEL reuse Sentinel-L7's exact env var
names and defaults (config/services.php: `env('OLLAMA_URL',
'http://localhost:11434')`, `env('OLLAMA_EMBEDDING_MODEL',
'nomic-embed-text')`) — same reasoning as GEMINI_API_KEY below: one shared
value covers both services in a local dev environment, and drift between
"what sentinel-eval assumes" and "what Sentinel-L7 actually runs" is
exactly the failure mode ADR-0001 warns about for this layer.
"""

from __future__ import annotations

import os


def synapse_l4_base_url() -> str:
    return os.environ.get("SYNAPSE_L4_BASE_URL", "http://localhost:8000").rstrip("/")


def sentinel_l7_mcp_url() -> str:
    return os.environ.get("SENTINEL_L7_MCP_URL", "http://localhost:8080/mcp")


def ollama_judge_host() -> str:
    return os.environ.get("OLLAMA_JUDGE_HOST", "http://100.82.223.70:11434").rstrip("/")


def ollama_judge_model() -> str:
    return os.environ.get("OLLAMA_JUDGE_MODEL", "qwen3.5:9b-q4_K_M")


def ollama_embedding_host() -> str:
    # Env var name matches Sentinel-L7's OLLAMA_URL exactly (config/services.php).
    return os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")


def ollama_embedding_model() -> str:
    return os.environ.get("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")


def gemini_api_key() -> str | None:
    return os.environ.get("GEMINI_API_KEY")


def gemini_flash_url() -> str:
    # Default matches sentinel-l7's config/services.php 'flash_url' exactly —
    # same env var name too, so a shared GEMINI_FLASH_URL override applies
    # to both services without needing to be set twice.
    return os.environ.get(
        "GEMINI_FLASH_URL",
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
    )


# Upstash Vector — same env var names as Sentinel-L7's config/services.php,
# no default URL/token (account-specific secrets, never guessable/safe to
# default). similarity_threshold's default (0.90) matches
# config/services.php's own env() fallback exactly.


def upstash_vector_url() -> str | None:
    return os.environ.get("UPSTASH_VECTOR_REST_URL")


def upstash_vector_token() -> str | None:
    return os.environ.get("UPSTASH_VECTOR_REST_TOKEN")


def upstash_vector_similarity_threshold() -> float:
    return float(os.environ.get("UPSTASH_VECTOR_THRESHOLD", "0.90"))


def upstash_vector_transactions_namespace() -> str:
    # Matches TransactionProcessorService::NAMESPACE in sentinel-l7 exactly —
    # not "default" (an earlier, looser reading of the ADR text assumed
    # that name; the real constant is "transactions").
    return "transactions"
