"""Layer 2: cross-provider / cross-run disagreement — not yet implemented.

Reuses infrastructure a system-under-test already has (e.g. Sentinel-L7's
dual-provider ComplianceDriver: Gemini vs OpenRouter) rather than building
new judge infrastructure. The harness stays domain-agnostic: it's given a
dict of named callables and just compares the labels/confidences they
produce for the same input.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sentinel_eval.models import EvalPrediction

# Each callable wraps one provider/config variant of the same
# system-under-test, e.g. {"gemini": sentinel_via_gemini, "openrouter":
# sentinel_via_openrouter}.
ProviderCall = Callable[[dict], EvalPrediction]


@dataclass
class DisagreementResult:
    prediction_id: str
    labels_by_provider: dict[str, str]
    confidence_by_provider: dict[str, float]
    agreed: bool
    confidence_spread: float


def score_disagreement(
    input_data: dict,
    providers: dict[str, ProviderCall],
) -> DisagreementResult:
    """Run `input_data` through each provider and compare their verdicts.

    TODO: implement once a system-under-test exposes multiple provider
    variants to compare (e.g. Sentinel-L7's ComplianceManager with
    Gemini vs OpenRouter drivers selected). Should:
      1. Call each provider in `providers` with `input_data`.
      2. Compare resulting `.label` values for exact agreement.
      3. Compute confidence spread (max - min) across providers.
      4. Populate and return a DisagreementResult — do not silently swallow
         a provider call failure; a provider that errors is itself a signal
         and should surface in the result rather than being dropped.
    """
    raise NotImplementedError("disagreement scoring is scaffolded, not implemented")
