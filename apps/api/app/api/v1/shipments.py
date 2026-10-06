"""Shipment endpoints (PLAN.md §11)."""

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedUser, require
from app.db.session import get_db
from app.schemas.shipment import ShipmentCreate, ShipmentEventRead, ShipmentList, ShipmentRead
from app.services.shipment import ShipmentService

router = APIRouter()


def _service(db: Session = Depends(get_db)) -> ShipmentService:
    return ShipmentService(db)


@router.post("", response_model=ShipmentRead, status_code=status.HTTP_202_ACCEPTED)
def create_shipment(
    payload: ShipmentCreate,
    service: ShipmentService = Depends(_service),
    user: AuthenticatedUser = Depends(require("shipment:create")),
) -> ShipmentRead:
    """Create a shipment and queue asynchronous processing.

    Returns 202 Accepted: the pipeline runs in the Celery worker. Without an
    uploaded artifact the task completes as a no-op; the artifact upload
    re-queues processing.
    """
    shipment = service.create_shipment(
        product=payload.product, version=payload.version, artifact_name=payload.artifact_name
    )
    return ShipmentRead.model_validate(shipment)


@router.get("", response_model=ShipmentList)
def list_shipments(
    product: str | None = Query(default=None, max_length=255),
    shipment_status: str | None = Query(default=None, alias="status", max_length=32),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: ShipmentService = Depends(_service),
    user: AuthenticatedUser = Depends(require("shipment:read")),
) -> ShipmentList:
    items, total = service.list_shipments(
        product=product, status=shipment_status, limit=limit, offset=offset
    )
    return ShipmentList(
        items=[ShipmentRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{shipment_id}", response_model=ShipmentRead)
def get_shipment(
    shipment_id: uuid.UUID,
    service: ShipmentService = Depends(_service),
    user: AuthenticatedUser = Depends(require("shipment:read")),
) -> ShipmentRead:
    return ShipmentRead.model_validate(service.get_shipment(shipment_id))


@router.get(
    "/{shipment_id}/events",
    response_model=list[ShipmentEventRead],
)
def get_shipment_events(
    shipment_id: uuid.UUID,
    service: ShipmentService = Depends(_service),
    user: AuthenticatedUser = Depends(require("shipment:read")),
) -> list[ShipmentEventRead]:
    events = service.get_events(shipment_id)
    return [ShipmentEventRead.model_validate(event) for event in events]


@router.post(
    "/{shipment_id}/retry",
    response_model=ShipmentRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_shipment(
    shipment_id: uuid.UUID,
    service: ShipmentService = Depends(_service),
    user: AuthenticatedUser = Depends(require("shipment:retry")),
) -> ShipmentRead:
    return ShipmentRead.model_validate(service.retry_shipment(shipment_id))


@router.post(
    "/{shipment_id}/publish",
    response_model=ShipmentRead,
    status_code=status.HTTP_200_OK,
)
def publish_shipment(
    shipment_id: uuid.UUID,
    service: ShipmentService = Depends(_service),
    user: AuthenticatedUser = Depends(require("shipment:publish")),
) -> ShipmentRead:
    """Publish a READY shipment. Idempotent: safe to call repeatedly.

    Returns 200 with the shipment; if already published, nothing changes.
    """
    shipment, _published = service.publish_shipment(shipment_id)
    return ShipmentRead.model_validate(shipment)
