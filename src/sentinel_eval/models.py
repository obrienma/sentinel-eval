"""Core data contracts for sentinel-eval.

These models are the only thing a system-under-test wrapper and the harness
share. Neither knows about Sentinel-L7's ComplianceDriver or Synapse-L4's
Axiom schema directly — each wrapper maps its own domain output into
EvalPrediction, and the harness only ever compares against `label`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EvalPrediction(BaseModel):
    """Normalized output of a system-under-test for a single input.

    `label` is intentionally a plain str, not a shared Literal enum —
    Sentinel's risk_level (low|medium|high|critical|unknown) and Synapse's
    status (nominal|degraded|critical) are different taxonomies. Forcing them
    into one enum would leak one service's domain vocabulary into the
    harness. See docs/adr/0001-standalone-module.md.
    """

    id: str
    raw_output: dict[str, Any]
    label: str
    confidence: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvalExample(BaseModel):
    """One labeled example for the offline (ground-truth) path."""

    input: dict[str, Any]
    expected_label: str


class EvalDataset(BaseModel):
    """A labeled dataset for offline scoring."""

    examples: list[EvalExample]

    def __len__(self) -> int:
        return len(self.examples)


class LabelMetrics(BaseModel):
    """Precision/recall/F1 for a single label value."""

    label: str
    precision: float
    recall: float
    f1: float
    support: int


class EvalReport(BaseModel):
    """Result of an offline run_eval() call."""

    total: int
    correct: int
    accuracy: float
    per_label: list[LabelMetrics]
    predictions: list[EvalPrediction]
