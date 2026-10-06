# ruff: noqa: I001  # worker_app.multiproc MUST be imported first (sets
# PROMETHEUS_MULTIPROC_DIR before app.core.metrics creates metric objects).
"""Worker observability: Prometheus exposition, queue gauge, task metrics."""

# Must run before app.core.metrics is imported (multiprocess value class).
import worker_app.multiproc  # noqa: F401

import logging
import threading
from typing import Any

from prometheus_client import start_http_server

from app.core.metrics import (
    exposition_registry,
    shipment_queue_size,
    worker_task_failures_total,
    worker_tasks_total,
)

logger = logging.getLogger(__name__)


def start_metrics_server(port: int, addr: str = "0.0.0.0") -> None:
    """Serve the aggregated Prometheus registry on a dedicated HTTP port."""
    start_http_server(port, addr=addr, registry=exposition_registry())
    logger.info(
        "metrics server started",
        extra={"service": "shipforge-worker", "metrics_port": port},
    )


def start_queue_monitor(redis_url: str, interval_seconds: float = 10.0) -> threading.Thread:
    """Background thread publishing the Celery queue depth as a gauge."""

    def _loop() -> None:
        import redis as redis_lib

        client = redis_lib.Redis.from_url(redis_url)
        while True:
            try:
                shipment_queue_size.set(client.llen("celery"))
            except Exception:  # noqa: BLE001 - monitoring must never crash the worker
                logger.debug("queue size probe failed", exc_info=True)
            threading.Event().wait(interval_seconds)

    thread = threading.Thread(target=_loop, name="queue-monitor", daemon=True)
    thread.start()
    return thread


def register_task_signals() -> None:
    """Wire Celery task lifecycle signals to worker task metrics."""
    from celery.signals import task_failure, task_postrun, task_prerun

    @task_prerun.connect(weak=False)
    def _prerun(sender: Any, **kwargs: Any) -> None:
        logger.debug(
            "task started",
            extra={"task_id": kwargs.get("task_id", ""), "task": getattr(sender, "name", "")},
        )

    @task_postrun.connect(weak=False)
    def _postrun(sender: Any, state: str = "SUCCESS", **kwargs: Any) -> None:
        worker_tasks_total.labels(
            task=getattr(sender, "name", "unknown"),
            outcome=state,
        ).inc()

    @task_failure.connect(weak=False)
    def _failure(sender: Any, **kwargs: Any) -> None:
        worker_task_failures_total.labels(task=getattr(sender, "name", "unknown")).inc()


def register_structured_logging(level: str = "INFO") -> None:
    """Keep Celery from replacing our JSON logging (PLAN.md §25).

    Celery installs its own handlers during worker startup and again in each
    prefork child; intercept both and return True to suppress its defaults.
    """
    from app.core.logging import configure_logging
    from celery.signals import setup_logging, worker_process_init

    def _install(**kwargs: Any) -> bool:
        configure_logging(
            service="shipforge-worker",
            level=level,
            extra_loggers=("celery", "celery.worker", "celery.task", "celery.trace", "kombu"),
        )
        return True  # skip Celery's default logging setup

    # weak=False: a local closure would be garbage-collected before firing.
    setup_logging.connect(_install, weak=False)
    worker_process_init.connect(_install, weak=False)
