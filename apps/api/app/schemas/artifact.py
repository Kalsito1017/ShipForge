"""Pydantic request/response schemas for artifacts."""

from pydantic import BaseModel, Field


class ArtifactRead(BaseModel):
    """Artifact metadata."""

    name: str
    path: str
    size: int
    content_type: str
    sha256: str


class ArtifactUploadResponse(BaseModel):
    """Response after an artifact upload."""

    shipment_id: str
    artifact: ArtifactRead
    queued: bool = Field(description="Whether pipeline processing was queued")
