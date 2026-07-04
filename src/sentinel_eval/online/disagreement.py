"""Layer 2: cross-provider / cross-run disagreement.

Reuses infrastructure a system-under-test already has (e.g. Sentinel-L7's
dual-provider ComplianceDriver: Gemini vs OpenRouter, via the per-request
driver override added in Sentinel-L7 Phase 3 step 6 — see
adapters/sentinel_l7.py's `driver` parameter) rather than building new judge
infrastructure. The harness stays domain-agnostic: it's given a dict of
named callables and just compares the labels/confidences they produce for
the same input.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from sentinel_eval.models import EvalPrediction
from sentinel_eval.observability import traced_layer

# Each callable wraps one provider/config variant of the same
# system-under-test, e.g. {"gemini": sentinel_via_gemini, "openrouter":
# sentinel_via_openrouter}.
ProviderCall = Callable[[dict], EvalPrediction]


@dataclass
class DisagreementResult:
    prediction_id: str
    labels_by_provider: dict[str, str]
    confidence_by_provider: dict[str, float]
    # A provider call failure is a signal, not something to drop silently —
    # populated with str(exception) for any provider whose call raised.
    errors_by_provider: dict[str, str] = field(default_factory=dict)
    agreed: bool = False
    confidence_spread: float = 0.0


@traced_layer("cross_provider_disagreement")
def score_disagreement(
    input_data: dict,
    providers: dict[str, ProviderCall],
) -> DisagreementResult:
    """Run `input_data` through each provider and compare their verdicts.

    `agreed` is only True when every provider answered (no errors) and all
    returned the exact same label — a provider that errors makes agreement
    unknowable, not automatically true, so it's treated as disagreement
    rather than silently excluded from the comparison.
    """
    prediction_id = input_data.get("id") or str(uuid.uuid4())
    labels: dict[str, str] = {}
    confidences: dict[str, float] = {}
    errors: dict[str, str] = {}

    for name, call in providers.items():
        try:
            prediction = call(input_data)
        except Exception as exc:
            errors[name] = str(exc)
            continue
        labels[name] = prediction.label
        confidences[name] = prediction.confidence

    agreed = len(errors) == 0 and len(labels) > 0 and len(set(labels.values())) == 1
    confidence_spread = (
        max(confidences.values()) - min(confidences.values()) if len(confidences) >= 2 else 0.0
    )

    return DisagreementResult(
        prediction_id=prediction_id,
        labels_by_provider=labels,
        confidence_by_provider=confidences,
        errors_by_provider=errors,
        agreed=agreed,
        confidence_spread=confidence_spread,
    )
