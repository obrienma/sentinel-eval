"""Layer 4: LLM-as-judge — best-effort, behind a circuit breaker.

Distinct from Sentinel-L7's existing `prompts/synapse-l4-judge.md`, which
scores `anomaly_score` for production routing of Axioms to AI audit. This
judge scores *eval quality* of a prediction that layers 1-3 have already
flagged as ambiguous — different purpose, different consumer. Do not
conflate the two.

Not required for the online path to function: on failure/timeout the chain
falls back Ollama -> Gemini Flash free tier -> heuristics-only, and judge
availability itself is tracked as a metric rather than hidden. Before this
judge is trusted to score unlabeled traffic, its verdicts should first be
validated against the labeled fixture dataset via the offline harness
(run_eval) — see docs/adr/0001-standalone-module.md.

This layer is reserved for the ambiguous tail flagged by layers 1-3; it is
not intended to run on every prediction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from sentinel_eval.models import EvalPrediction

logger = logging.getLogger(__name__)


class JudgeSource(str, Enum):
    OLLAMA = "ollama"
    GEMINI_FLASH = "gemini_flash"
    HEURISTICS_FALLBACK = "heuristics_fallback"


@dataclass
class JudgeVerdict:
    prediction_id: str
    source: JudgeSource
    # None when the chain fell all the way back to heuristics-only and no
    # judge model produced an opinion.
    verdict_label: str | None = None
    reasoning: str | None = None


@dataclass
class JudgeMetrics:
    """Availability tracking — logged as a first-class metric, not hidden.

    `% ambiguous transactions scored by judge vs fallback` per the ADR.
    """

    total_judged: int = 0
    scored_by_ollama: int = 0
    scored_by_gemini_flash: int = 0
    scored_by_heuristics_fallback: int = 0

    def record(self, source: JudgeSource) -> None:
        self.total_judged += 1
        if source is JudgeSource.OLLAMA:
            self.scored_by_ollama += 1
        elif source is JudgeSource.GEMINI_FLASH:
            self.scored_by_gemini_flash += 1
        else:
            self.scored_by_heuristics_fallback += 1

    @property
    def pct_scored_by_judge(self) -> float:
        if self.total_judged == 0:
            return 0.0
        judged = self.scored_by_ollama + self.scored_by_gemini_flash
        return judged / self.total_judged


def _call_ollama(prediction: EvalPrediction, context: str) -> str:
    """TODO: call remote Ollama over Tailscale (partner-owned host).

    Must raise (e.g. httpx.TimeoutException, httpx.ConnectError, or a
    custom JudgeUnavailable) on failure/timeout so the circuit breaker can
    fall through to the next source — do not return a sentinel value.
    """
    raise NotImplementedError("Ollama judge call not yet implemented")


def _call_gemini_flash(prediction: EvalPrediction, context: str) -> str:
    """TODO: call Gemini Flash free tier as the secondary fallback.

    Same contract as _call_ollama: raise on failure/timeout, don't swallow.
    """
    raise NotImplementedError("Gemini Flash fallback call not yet implemented")


@dataclass
class JudgeCircuitBreaker:
    """Ollama -> Gemini Flash -> heuristics-only, with availability tracked."""

    metrics: JudgeMetrics = field(default_factory=JudgeMetrics)

    def judge(self, prediction: EvalPrediction, context: str) -> JudgeVerdict:
        """Attempt to get a judge verdict for an ambiguous prediction.

        `context` is caller-supplied evidence for why this prediction was
        flagged (e.g. the heuristic flags / disagreement / consistency
        results from layers 1-3) — TODO: define once those layers exist.
        """
        # NotImplementedError is re-raised rather than treated as a
        # fallback trigger: until _call_ollama/_call_gemini_flash are wired
        # up, calling judge() should fail loudly, not silently report every
        # verdict as heuristics_fallback.
        try:
            label = _call_ollama(prediction, context)
            self.metrics.record(JudgeSource.OLLAMA)
            return JudgeVerdict(
                prediction_id=prediction.id,
                source=JudgeSource.OLLAMA,
                verdict_label=label,
            )
        except NotImplementedError:
            raise
        except Exception:
            logger.warning(
                "ollama judge unavailable for prediction %s, falling back to gemini flash",
                prediction.id,
            )

        try:
            label = _call_gemini_flash(prediction, context)
            self.metrics.record(JudgeSource.GEMINI_FLASH)
            return JudgeVerdict(
                prediction_id=prediction.id,
                source=JudgeSource.GEMINI_FLASH,
                verdict_label=label,
            )
        except NotImplementedError:
            raise
        except Exception:
            logger.warning(
                "gemini flash judge unavailable for prediction %s, falling back to heuristics-only",
                prediction.id,
            )

        self.metrics.record(JudgeSource.HEURISTICS_FALLBACK)
        return JudgeVerdict(
            prediction_id=prediction.id,
            source=JudgeSource.HEURISTICS_FALLBACK,
            verdict_label=None,
            reasoning="judge chain exhausted; no LLM opinion available",
        )
