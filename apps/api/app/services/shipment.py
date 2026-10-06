"""Shipment business logic."""

import logging
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.core.metrics import shipments_created_total, shipments_published_total
from app.models.shipment import Shipment, ShipmentEvent, ShipmentLog
from app.repositories.shipment_repository import ShipmentRepository
from app.services import state_machine

logger = logging.getLogger(__name__)


class ShipmentService:
    """Application service orchestrating shipment lifecycle operations."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = ShipmentRepository(session)

    def create_shipment(self, *, product: str, version: str, artifact_name: str | None) -> Shipment:
        """Create a shipment in CREATED state and record the creation event."""
        shipment = Shipment(
            product=product,
            version=version,
            artifact_name=artifact_name,
            status=state_machine.CREATED,
        )
        try:
            self._repo.add(shipment)
        except IntegrityError as exc:
            self._session.rollback()
            raise ConflictError(
                f"Shipment for {product} {version} already exists",
                product=product,
                version=version,
            ) from exc

        self._session.add(
            ShipmentEvent(
                id=uuid.uuid4(),
                shipment_id=shipment.id,
                event_type=state_machine.CREATED,
                message="Shipment created",
                meta={"from": None, "to": state_machine.CREATED},
            )
        )
        self._session.flush()
        # Commit before dispatching: the worker must see the row.
        self._session.commit()
        shipments_created_total.inc()
        queue_processing(shipment)
        return shipment

    def get_shipment(self, shipment_id: uuid.UUID, *, for_update: bool = False) -> Shipment:
        """Return a shipment or raise NotFoundError.

        ``for_update`` takes a row lock — use it on paths that transition
        state so concurrent requests cannot double-apply an event.
        """
        shipment = self._repo.get(shipment_id, for_update=for_update)
        if shipment is None:
            raise NotFoundError("Shipment not found", shipment_id=str(shipment_id))
        return shipment

    def list_shipments(
        self,
        *,
        product: str | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Shipment], int]:
        """List shipments with optional filters and pagination."""
        return self._repo.list_shipments(
            product=product, status=status, limit=limit, offset=offset
        )

    def get_events(self, shipment_id: uuid.UUID) -> list[ShipmentEvent]:
        """Return the ordered event trail for a shipment."""
        self.get_shipment(shipment_id)
        return self._repo.list_events(shipment_id)

    def get_logs(
        self, shipment_id: uuid.UUID, *, limit: int = 200, offset: int = 0
    ) -> tuple[list[ShipmentLog], int]:
        """Return structured log lines for a shipment."""
        self.get_shipment(shipment_id)
        return self._repo.list_logs(shipment_id, limit=limit, offset=offset)

    def retry_shipment(self, shipment_id: uuid.UUID) -> Shipment:
        """Move a FAILED shipment back to VALIDATING and queue processing."""
        shipment = self.get_shipment(shipment_id, for_update=True)
        if shipment.status != state_machine.FAILED:
            raise ConflictError(
                f"Only FAILED shipments can be retried (current: {shipment.status})",
                shipment_id=str(shipment_id),
                status=shipment.status,
            )
        state_machine.transition(
            self._session,
            shipment,
            state_machine.VALIDATING,
            event_type="RETRY",
            message="Shipment retry requested",
        )
        self._session.commit()
        queue_processing(shipment)
        return shipment

    def publish_shipment(self, shipment_id: uuid.UUID) -> tuple[Shipment, bool]:
        """Publish a READY shipment. Idempotent: already-published is a no-op.

        Returns the shipment and whether this call performed the publication.
        """
        shipment = self.get_shipment(shipment_id, for_update=True)

        if shipment.status == state_machine.PUBLISHED:
            return shipment, False

        if shipment.status != state_machine.READY:
            raise ConflictError(
                f"Only READY shipments can be published (current: {shipment.status})",
                shipment_id=str(shipment_id),
                status=shipment.status,
            )

        state_machine.transition(
            self._session,
            shipment,
            state_machine.PUBLISHED,
            event_type="PUBLISHED",
            message="Shipment published",
        )
        shipments_published_total.inc()
        logger.info(
            "shipment published",
            extra={"shipment_id": str(shipment.id), "stage": state_machine.PUBLISHED},
        )
        return shipment, True


def queue_processing(shipment: Shipment) -> None:
    """Enqueue the async pipeline for a shipment (Celery task dispatch)."""
    from app.core.queue import queue_processing as dispatch

    task_id = dispatch(shipment.id)
    logger.info(
        "pipeline dispatch requested",
        extra={
            "shipment_id": str(shipment.id),
            "task_id": task_id,
            "stage": state_machine.VALIDATING,
        },
    )
