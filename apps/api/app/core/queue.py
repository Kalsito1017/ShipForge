"""Task queue bridge: the API enqueues pipeline work for the Celery worker.

The API only ever *dispatches* tasks by name — it never imports worker code.
"""

import logging
import uuid
from typing import Any, cast

from celery import Celery

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Registered task names (must match worker_app.tasks registrations).
PROCESS_SHIPMENT_TASK = "tasks.pipeline.process_shipment"

_dispatch: Any = None


def _get_producer() -> Celery:
    """Return a producer-only Celery client bound to the configured broker."""
    global _dispatch
    if _dispatch is None:
        settings = get_settings()
        _dispatch = Celery("shipforge-api", broker=settings.redis_url, backend=settings.redis_url)
        _dispatch.conf.task_ignore_result = True
    return _dispatch


def queue_processing(shipment_id: uuid.UUID) -> str | None:
    """Enqueue the pipeline for a shipment. Returns the Celery task id.

    Returns None when dispatch fails; callers log and continue — the shipment
    can always be re-queued via POST /shipments/{id}/retry.
    """
    try:
        result = _get_producer().send_task(PROCESS_SHIPMENT_TASK, args=[str(shipment_id)])
        logger.info(
            "pipeline queued",
            extra={"shipment_id": str(shipment_id), "task_id": result.id},
        )
        return cast(str, result.id)
    except Exception:
        logger.exception(
            "failed to queue pipeline",
            extra={"shipment_id": str(shipment_id), "error_code": "DEPENDENCY_ERROR"},
        )
        return None


def reset_producer() -> None:
    """Drop the cached producer (used by tests)."""
    global _dispatch
    _dispatch = None
