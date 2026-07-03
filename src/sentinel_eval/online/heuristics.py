"""Layer 1: rule-based heuristics — free, deterministic, always available.

These checks operate only on the normalized EvalPrediction envelope (plus
its untouched raw_output dict), so they carry no Sentinel-specific or
Synapse-specific assumptions. Checks that reference optional raw_output
fields (e.g. a "narrative" key) use `.get()` defensively and simply never
fire for systems-under-test whose payload doesn't have that field.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sentinel_eval.models import EvalPrediction

# Labels that read as "elevated concern" across both known taxonomies
# (Sentinel's risk_level, Synapse's status). Callers scoring a system with a
# different vocabulary can override via the `elevated_labels` parameter.
DEFAULT_ELEVATED_LABELS = frozenset({"critical", "high", "degraded"})


@dataclass
class HeuristicFlag:
    reason: str
    severity: float  # 0.0-1.0, higher = more suspicious


@dataclass
class HeuristicResult:
    prediction_id: str
    flagged: bool
    flags: list[HeuristicFlag] = field(default_factory=list)
    suspicion_score: float = 0.0  # max severity across flags, 0.0 if none


def check_confidence_threshold(
    prediction: EvalPrediction,
    *,
    low: float = 0.4,
    high: float = 0.98,
) -> HeuristicFlag | None:
    """Flag predictions with implausibly low or suspiciously saturated confidence."""
    if prediction.confidence < low:
        return HeuristicFlag(
            reason=f"confidence {prediction.confidence:.2f} below low threshold {low}",
            severity=1.0 - prediction.confidence,
        )
    if prediction.confidence > high:
        return HeuristicFlag(
            reason=f"confidence {prediction.confidence:.2f} above saturation threshold {high}",
            severity=0.3,
        )
    return None


def check_elevated_label_low_confidence(
    prediction: EvalPrediction,
    *,
    elevated_labels: frozenset[str] = DEFAULT_ELEVATED_LABELS,
    confidence_floor: float = 0.6,
) -> HeuristicFlag | None:
    """Flag a severe-sounding label paired with unconvincing confidence."""
    if (
        prediction.label.lower() in elevated_labels
        and prediction.confidence < confidence_floor
    ):
        return HeuristicFlag(
            reason=(
                f"label {prediction.label!r} is elevated but confidence "
                f"{prediction.confidence:.2f} is below {confidence_floor}"
            ),
            severity=confidence_floor - prediction.confidence,
        )
    return None


def check_narrative_confidence_contradiction(
    prediction: EvalPrediction,
) -> HeuristicFlag | None:
    """Flag a missing narrative/explanation alongside high confidence.

    Opportunistic check: only fires when raw_output actually has a
    "narrative" key (e.g. Sentinel-L7's ComplianceDriver output). No-ops for
    payloads without one.
    """
    if "narrative" not in prediction.raw_output:
        return None
    narrative = prediction.raw_output.get("narrative")
    if not narrative and prediction.confidence >= 0.8:
        return HeuristicFlag(
            reason="narrative missing/empty despite high confidence",
            severity=0.5,
        )
    return None


DEFAULT_CHECKS = (
    check_confidence_threshold,
    check_elevated_label_low_confidence,
    check_narrative_confidence_contradiction,
)


def run_heuristics(
    prediction: EvalPrediction,
    checks=DEFAULT_CHECKS,
) -> HeuristicResult:
    """Run all heuristic checks against a single prediction."""
    flags = [flag for check in checks if (flag := check(prediction)) is not None]
    suspicion_score = max((f.severity for f in flags), default=0.0)
    return HeuristicResult(
        prediction_id=prediction.id,
        flagged=bool(flags),
        flags=flags,
        suspicion_score=suspicion_score,
    )
