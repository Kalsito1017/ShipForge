"""Application metrics (PLAN.md §24) shared by API and worker.

Both processes expose their own registry on a /metrics endpoint; Prometheus
scrapes both and sums. Names are stable and part of the observability contract.

Celery note: tasks execute in *forked child processes*, whose counter updates
would be invisible to a registry served by the parent. When
``PROMETHEUS_MULTIPROC_DIR`` is set (worker bootstrap does this), values are
written to shared memory files and ``exposition_registry()`` aggregates them.
"""

import os
from collections.abc import Callable
from time import monotonic

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)

# Registry is per-process; API and worker each expose theirs separately.
REGISTRY = CollectorRegistry(auto_describe=True)

_MULTIPROC_DIR = os.environ.get("PROMETHEUS_MULTIPROC_DIR")

# --- Shipment lifecycle ---------------------------------------------------

shipments_created_total = Counter(
    "shipments_created_total",
    "Shipments created",
    registry=REGISTRY,
)

shipments_failed_total = Counter(
    "shipments_failed_total",
    "Shipments that ended in FAILED",
    ["stage", "error_code"],
    registry=REGISTRY,
)

shipments_published_total = Counter(
    "shipments_published_total",
    "Shipments published successfully",
    registry=REGISTRY,
)

shipment_processing_duration_seconds = Histogram(
    "shipment_processing_duration_seconds",
    "End-to-end shipment processing duration",
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300),
    registry=REGISTRY,
)

shipment_queue_size = Gauge(
    "shipment_queue_size",
    "Pending pipeline tasks in the Celery queue",
    multiprocess_mode="mostrecent",
    registry=REGISTRY,
)

# --- API ------------------------------------------------------------------

api_requests_total = Counter(
    "api_requests_total",
    "API HTTP requests",
    ["method", "path", "status"],
    registry=REGISTRY,
)

api_request_duration_seconds = Histogram(
    "api_request_duration_seconds",
    "API HTTP request latency",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
    registry=REGISTRY,
)

# --- Worker ---------------------------------------------------------------

worker_tasks_total = Counter(
    "worker_tasks_total",
    "Celery tasks executed",
    ["task", "outcome"],
    registry=REGISTRY,
)

worker_task_failures_total = Counter(
    "worker_task_failures_total",
    "Celery tasks that raised an exception",
    ["task"],
    registry=REGISTRY,
)


def exposition_registry() -> CollectorRegistry:
    """Registry to serve on /metrics.

    In multiprocess mode (Celery workers) aggregate the shared memory files;
    otherwise expose this process's own registry.
    """
    if _MULTIPROC_DIR:
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
        return registry
    return REGISTRY


def render_metrics() -> tuple[bytes, str]:
    """Return (payload, content_type) for a /metrics response."""
    return generate_latest(exposition_registry()), CONTENT_TYPE_LATEST


class Timer:
    """Context manager measuring elapsed seconds for a histogram."""

    def __init__(self, histogram: Histogram, **labels: str) -> None:
        self._histogram = histogram
        self._labels = labels
        self._start = 0.0

    def __enter__(self) -> "Timer":
        self._start = monotonic()
        return self

    def __exit__(self, *exc: object) -> None:
        self._histogram.labels(**self._labels).observe(monotonic() - self._start)


def observe_request(method: str, path: str, status: int, duration: float) -> None:
    """Record one API request (used by the instrumentation middleware)."""
    api_requests_total.labels(method=method, path=path, status=str(status)).inc()
    api_request_duration_seconds.labels(method=method, path=path).observe(duration)


def timed(
    histogram: Histogram, **labels: str
) -> Callable[[Callable[..., object]], Callable[..., object]]:
    """Decorator observing a callable's duration on the given histogram."""

    def decorator(func: Callable[..., object]) -> Callable[..., object]:
        def wrapper(*args: object, **kwargs: object) -> object:
            with Timer(histogram, **labels):
                return func(*args, **kwargs)

        wrapper.__name__ = getattr(func, "__name__", "wrapped")
        return wrapper

    return decorator
