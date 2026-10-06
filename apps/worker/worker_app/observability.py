"""Worker observability: Prometheus exposition, queue gauge, task metrics."""

import logging
import threading
from typing import Any

from prometheus_client import start_http_server

from app.core.metrics import (
    REGISTRY,
    shipment_queue_size,
    worker_task_failures_total,
    worker_tasks_total,
)

logger = logging.getLogger(__name__)


def start_metrics_server(port: int, addr: str = "0.0.0.0") -> None:
    """Serve the worker's Prometheus registry on a dedicated HTTP port."""
    start_http_server(port, addr=addr, registry=REGISTRY)
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

    @task_prerun.connect
    def _prerun(sender: Any, **kwargs: Any) -> None:
        logger.debug(
            "task started",
            extra={"task_id": kwargs.get("task_id", ""), "task": getattr(sender, "name", "")},
        )

    @task_postrun.connect
    def _postrun(sender: Any, state: str = "SUCCESS", **kwargs: Any) -> None:
        worker_tasks_total.labels(
            task=getattr(sender, "name", "unknown"),
            outcome=state,
        ).inc()

    @task_failure.connect
    def _failure(sender: Any, **kwargs: Any) -> None:
        worker_task_failures_total.labels(task=getattr(sender, "name", "unknown")).inc()
