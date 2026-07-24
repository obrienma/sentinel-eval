"""MeterProvider setup — same eager-at-import pattern as tracing.py.

Same OTLP HTTP Collector endpoint as traces, exporting to /v1/metrics
instead of /v1/traces (Collector -> Prometheus, per the suite's
observability stack).
"""

from __future__ import annotations

from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

from arbiter_l8.models import EvalReport
from arbiter_l8.observability._env import otlp_endpoint, service_name

# No explicit force_flush() is needed anywhere in this codebase, including
# for a one-shot run_eval() invocation that exits right after recording its
# gauge readings: MeterProvider registers an atexit hook, and
# PeriodicExportingMetricReader's background thread runs one final collect()
# + export the moment shutdown() fires — before the 60s default
# export_interval_millis would otherwise elapse. Verified live against a
# real Collector: a script that calls the judge circuit breaker once and
# exits normally (no force_flush call) still lands in Prometheus. The only
# case this doesn't cover is a hard process kill (SIGKILL/OOM) that skips
# atexit entirely — a risk every OTel-instrumented service in this suite
# already accepts, not something specific to arbiter-l8.
_reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(endpoint=f"{otlp_endpoint()}/v1/metrics")
)
_provider = MeterProvider(
    resource=Resource.create({"service.name": service_name()}),
    metric_readers=[_reader],
)
metrics.set_meter_provider(_provider)

meter = metrics.get_meter("arbiter_l8")

judge_outcome_counter = meter.create_counter(
    "arbiter_l8.judge.outcome",
    unit="1",
    description=(
        "Judge-layer resolutions by source (ollama/gemini_flash/heuristics_fallback) — "
        "the '% scored by judge vs fallback' signal from docs/adr/0001"
    ),
)

layer_latency_histogram = meter.create_histogram(
    "arbiter_l8.layer.latency",
    unit="ms",
    description="Per-layer latency for online scoring layers",
)

harness_metric_gauge = meter.create_gauge(
    "arbiter_l8.harness.metric",
    unit="1",
    description=(
        "Precision/recall/F1/accuracy from an offline run_eval() run, "
        "recorded once per run so Grafana can plot it as a time series"
    ),
)


def record_harness_metrics(report: EvalReport) -> None:
    """Emit one gauge reading per label per metric, plus an overall accuracy row.

    Called once at the end of run_eval() — not per example — so each
    harness run shows up as one set of points, letting a prompt/model
    change show up as a step change in Grafana.
    """
    harness_metric_gauge.set(report.accuracy, {"metric": "accuracy", "label": "overall"})
    for label_metrics in report.per_label:
        harness_metric_gauge.set(
            label_metrics.precision, {"metric": "precision", "label": label_metrics.label}
        )
        harness_metric_gauge.set(
            label_metrics.recall, {"metric": "recall", "label": label_metrics.label}
        )
        harness_metric_gauge.set(
            label_metrics.f1, {"metric": "f1", "label": label_metrics.label}
        )
