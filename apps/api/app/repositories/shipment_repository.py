"""Shipment repository — all shipment queries live here."""

import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.shipment import Shipment, ShipmentEvent


class ShipmentRepository:
    """Persistence operations for shipments and their events."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, shipment: Shipment) -> Shipment:
        self._session.add(shipment)
        self._session.flush()
        return shipment

    def get(self, shipment_id: uuid.UUID, *, for_update: bool = False) -> Shipment | None:
        """Return a shipment; ``for_update`` takes a row lock (serialize runs)."""
        if for_update:
            stmt = select(Shipment).where(Shipment.id == shipment_id).with_for_update()
            return self._session.scalars(stmt).first()
        return self._session.get(Shipment, shipment_id)

    def get_by_product_version(self, product: str, version: str) -> Shipment | None:
        stmt = select(Shipment).where(Shipment.product == product, Shipment.version == version)
        return self._session.scalars(stmt).first()

    def list_shipments(
        self,
        *,
        product: str | None = None,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[Shipment], int]:
        stmt = self._filtered(product=product, status=status)
        total = self._session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self._session.scalars(
            stmt.order_by(Shipment.created_at.desc()).limit(limit).offset(offset)
        ).all()
        return list(rows), int(total)

    def list_events(self, shipment_id: uuid.UUID) -> list[ShipmentEvent]:
        stmt = (
            select(ShipmentEvent)
            .where(ShipmentEvent.shipment_id == shipment_id)
            .order_by(ShipmentEvent.created_at.asc())
        )
        return list(self._session.scalars(stmt).all())

    def _filtered(self, *, product: str | None, status: str | None) -> Select[Shipment]:
        stmt = select(Shipment)
        if product is not None:
            stmt = stmt.where(Shipment.product == product)
        if status is not None:
            stmt = stmt.where(Shipment.status == status)
        return stmt
