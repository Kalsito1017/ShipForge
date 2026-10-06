"""Celery tasks: asynchronous shipment pipeline processing."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import configure_logging, get_logger
from app.core.storage import get_storage
from app.db.session import get_session_factory
from worker_app.celery_app import celery_app
from worker_app.core.config import get_settings
from worker_app.observability import (
    register_task_signals,
    start_metrics_server,
    start_queue_monitor,
)
from worker_app.services.pipeline import PipelineRunner

logger = get_logger(__name__)

_settings = get_settings()
configure_logging(service="shipforge-worker", level=_settings.log_level)

# Observability: Prometheus exposition + queue depth + task counters.
start_metrics_server(_settings.metrics_port)
start_queue_monitor(_settings.redis_url)
register_task_signals()


def _run_in_session(shipment_id: str) -> dict[str, Any]:
    """Run the pipeline in a dedicated database session."""
    factory = get_session_factory()
    session: Session = factory()
    try:
        runner = PipelineRunner(session, get_storage())
        result = runner.run(uuid.UUID(shipment_id))
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@celery_app.task(
    name="tasks.pipeline.process_shipment",
    bind=True,
    max_retries=3,
    default_retry_delay=5,
    acks_late=True,
)
def process_shipment(self: Any, shipment_id: str) -> dict[str, Any]:
    """Process a shipment through Validate -> Build -> Scan -> Publish.

    Idempotent: re-delivery resumes from the current status and never
    publishes twice. Transient errors are retried with a short delay.
    """
    logger.info(
        "pipeline task started",
        extra={"shipment_id": shipment_id, "task_id": self.request.id or ""},
    )
    try:
        result = _run_in_session(shipment_id)
    except Exception as exc:
        logger.exception(
            "pipeline task error",
            extra={"shipment_id": shipment_id, "task_id": self.request.id or ""},
        )
        raise self.retry(exc=exc) from exc

    logger.info(
        "pipeline task finished",
        extra={
            "shipment_id": shipment_id,
            "task_id": self.request.id or "",
            "stage": result.get("outcome", ""),
        },
    )
    return result
