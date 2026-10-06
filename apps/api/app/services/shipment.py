"""Shipment business logic."""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.shipment import Shipment, ShipmentEvent
from app.repositories.shipment_repository import ShipmentRepository
from app.services import state_machine


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
        return shipment

    def get_shipment(self, shipment_id: uuid.UUID) -> Shipment:
        """Return a shipment or raise NotFoundError."""
        shipment = self._repo.get(shipment_id)
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

    def retry_shipment(self, shipment_id: uuid.UUID) -> Shipment:
        """Move a FAILED shipment back to VALIDATING and queue processing."""
        shipment = self.get_shipment(shipment_id)
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
        queue_processing(shipment)
        return shipment


def queue_processing(shipment: Shipment) -> None:
    """Hook for enqueueing the async pipeline (Celery lands in M2).

    Currently a no-op that only logs; keep the call sites so M2 can wire the
    task dispatch in one place.
    """
    import logging

    logging.getLogger(__name__).info(
        "pipeline queued (stub)",
        extra={"shipment_id": str(shipment.id), "stage": state_machine.VALIDATING},
    )
