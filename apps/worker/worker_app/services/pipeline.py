"""Pipeline orchestration with resume and idempotency semantics (PLAN.md §15).

The pipeline is resumable: the task re-entry point inspects the shipment's
current status and continues from the corresponding stage. This is what makes
Celery retries and duplicate deliveries safe — completed stages are never
re-executed, and a shipment is never published twice.

Stage mapping (stage name -> status it runs in -> next status):

    validate : VALIDATING -> BUILDING
    build    : BUILDING   -> SCANNING
    scan     : SCANNING   -> READY
    publish  : READY      -> PUBLISHED
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import InvalidTransitionError
from app.core.logging import get_logger
from app.core.metrics import (
    shipment_processing_duration_seconds,
    shipments_failed_total,
    shipments_published_total,
)
from app.core.storage import ArtifactStorage
from app.models.shipment import Shipment
from app.services import state_machine as sm
from worker_app.services.stages import PipelineStages, StageResult

logger = get_logger(__name__)

# (status the stage runs in, stage method name, next status on success)
STAGE_SEQUENCE: tuple[tuple[str, str, str], ...] = (
    (sm.VALIDATING, "validate", sm.BUILDING),
    (sm.BUILDING, "build", sm.SCANNING),
    (sm.SCANNING, "scan", sm.READY),
    (sm.READY, "publish", sm.PUBLISHED),
)


class PipelineRunner:
    """Executes the shipment pipeline from whatever stage the shipment is at."""

    def __init__(self, session: Session, storage: ArtifactStorage) -> None:
        self._session = session
        self._stages = PipelineStages(session, storage)

    def run(self, shipment_id: uuid.UUID) -> dict[str, Any]:
        """Process a shipment to completion. Safe to call repeatedly."""
        shipment = self._session.get(Shipment, shipment_id)
        if shipment is None:
            logger.warning(
                "pipeline: shipment not found",
                extra={"shipment_id": str(shipment_id)},
            )
            return {"shipment_id": str(shipment_id), "outcome": "not_found"}

        if shipment.status == sm.PUBLISHED:
            # Idempotent no-op: never publish twice.
            logger.info(
                "pipeline: already published, skipping",
                extra={"shipment_id": str(shipment_id), "stage": sm.PUBLISHED},
            )
            return {"shipment_id": str(shipment_id), "outcome": "already_published"}

        if shipment.status == sm.FAILED:
            # Failed shipments need an explicit retry (FAILED -> VALIDATING).
            logger.info(
                "pipeline: shipment failed, skipping",
                extra={
                    "shipment_id": str(shipment_id),
                    "stage": sm.FAILED,
                    "error_code": shipment.error_code,
                },
            )
            return {
                "shipment_id": str(shipment_id),
                "outcome": "failed",
                "error_code": shipment.error_code,
            }

        # No artifact yet: wait for the upload (which re-dispatches the task)
        # instead of failing. Keeps POST /shipments and upload order-agnostic.
        if not shipment.artifact_path:
            logger.info(
                "pipeline: awaiting artifact upload",
                extra={"shipment_id": str(shipment_id), "stage": shipment.status},
            )
            return {"shipment_id": str(shipment_id), "outcome": "awaiting_artifact"}

        if shipment.status == sm.CREATED:
            self._advance(shipment, sm.VALIDATING, event_type="PIPELINE_STARTED")

        outcome = self._run_stages(shipment)
        self._session.commit()
        return outcome

    def _run_stages(self, shipment: Shipment) -> dict[str, Any]:
        results: list[dict[str, Any]] = []

        for status_name, method_name, next_status in STAGE_SEQUENCE:
            if shipment.status != status_name:
                continue  # stage already completed (resume semantics)

            result: StageResult = getattr(self._stages, method_name)(shipment)
            results.append(
                {
                    "stage": result.stage,
                    "ok": result.ok,
                    "duration_seconds": round(result.duration_seconds, 3),
                }
            )

            if not result.ok:
                self._fail(
                    shipment,
                    result.error_code or "INTERNAL_ERROR",
                    result.error_message or "stage failed",
                )
                shipments_failed_total.labels(
                    stage=result.stage,
                    error_code=result.error_code or "INTERNAL_ERROR",
                ).inc()
                return {
                    "shipment_id": str(shipment.id),
                    "outcome": "failed",
                    "stage": result.stage,
                    "error_code": result.error_code,
                    "stages": results,
                }

            self._advance(
                shipment,
                next_status,
                event_type="PUBLISHED" if next_status == sm.PUBLISHED else "STAGE_COMPLETED",
                message=(
                    "Shipment published"
                    if next_status == sm.PUBLISHED
                    else f"{status_name} stage completed"
                ),
                context={"completed_stage": status_name},
            )

        if shipment.status == sm.PUBLISHED:
            shipments_published_total.inc()
            self._observe_duration(shipment)
        return {
            "shipment_id": str(shipment.id),
            "outcome": "published" if shipment.status == sm.PUBLISHED else shipment.status,
            "stages": results,
        }

    def _observe_duration(self, shipment: Shipment) -> None:
        """Record end-to-end processing duration when known."""
        if shipment.created_at is None:
            return
        created = shipment.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - created).total_seconds()
        if elapsed >= 0:
            shipment_processing_duration_seconds.observe(elapsed)

    def _advance(
        self,
        shipment: Shipment,
        new_status: str,
        *,
        event_type: str,
        message: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        try:
            sm.transition(
                self._session,
                shipment,
                new_status,
                event_type=event_type,
                message=message or f"Pipeline entering {new_status}",
                context=context,
            )
        except InvalidTransitionError:
            # A concurrent/duplicate run already advanced the shipment; the
            # status check in _run_stages keeps the pipeline idempotent.
            logger.info(
                "pipeline: transition already applied",
                extra={"shipment_id": str(shipment.id), "stage": new_status},
            )

    def _fail(self, shipment: Shipment, error_code: str, error_message: str) -> None:
        try:
            sm.transition(
                self._session,
                shipment,
                sm.FAILED,
                event_type="PIPELINE_FAILED",
                message=error_message,
                error_code=error_code,
                error_message=error_message,
            )
        except InvalidTransitionError:
            logger.info(
                "pipeline: failure already recorded",
                extra={"shipment_id": str(shipment.id), "error_code": error_code},
            )
