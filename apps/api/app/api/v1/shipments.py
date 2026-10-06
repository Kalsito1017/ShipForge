"""Shipment endpoints (PLAN.md §11)."""

import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.shipment import ShipmentCreate, ShipmentEventRead, ShipmentList, ShipmentRead
from app.services.shipment import ShipmentService

router = APIRouter()


def _service(db: Session = Depends(get_db)) -> ShipmentService:
    return ShipmentService(db)


@router.post("", response_model=ShipmentRead, status_code=status.HTTP_201_CREATED)
def create_shipment(
    payload: ShipmentCreate, service: ShipmentService = Depends(_service)
) -> ShipmentRead:
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
    shipment_id: uuid.UUID, service: ShipmentService = Depends(_service)
) -> ShipmentRead:
    return ShipmentRead.model_validate(service.get_shipment(shipment_id))


@router.get(
    "/{shipment_id}/events",
    response_model=list[ShipmentEventRead],
)
def get_shipment_events(
    shipment_id: uuid.UUID, service: ShipmentService = Depends(_service)
) -> list[ShipmentEventRead]:
    events = service.get_events(shipment_id)
    return [ShipmentEventRead.model_validate(event) for event in events]


@router.post(
    "/{shipment_id}/retry",
    response_model=ShipmentRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_shipment(
    shipment_id: uuid.UUID, service: ShipmentService = Depends(_service)
) -> ShipmentRead:
    return ShipmentRead.model_validate(service.retry_shipment(shipment_id))
