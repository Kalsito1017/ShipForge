"""Pydantic request/response schemas for the shipment API."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ShipmentCreate(BaseModel):
    """Request body for creating a shipment."""

    product: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9._-]+$")
    version: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._+-]+$")
    artifact_name: str | None = Field(default=None, max_length=512)


class ShipmentRead(BaseModel):
    """Shipment representation returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product: str
    version: str
    artifact_name: str | None
    artifact_path: str | None
    status: str
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None


class ShipmentEventRead(BaseModel):
    """A single shipment lifecycle event."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    shipment_id: uuid.UUID
    event_type: str
    message: str
    metadata: dict[str, Any] | None = Field(default=None, validation_alias="meta")
    created_at: datetime


class ShipmentList(BaseModel):
    """Paginated shipment listing."""

    items: list[ShipmentRead]
    total: int
    limit: int
    offset: int
