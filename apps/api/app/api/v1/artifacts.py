"""Artifact endpoints (PLAN.md §15): upload and download."""

import uuid

from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.artifacts import sha256_of
from app.core.exceptions import AppError
from app.db.session import get_db
from app.schemas.artifact import ArtifactRead, ArtifactUploadResponse
from app.services.artifact import ArtifactService
from app.services.shipment import queue_processing

router = APIRouter()


def _service(db: Session = Depends(get_db)) -> ArtifactService:
    return ArtifactService(db)


@router.post(
    "/{shipment_id}/artifact",
    response_model=ArtifactUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def upload_artifact(
    shipment_id: uuid.UUID,
    file: UploadFile = File(...),
    service: ArtifactService = Depends(_service),
) -> ArtifactUploadResponse:
    """Upload an artifact and queue pipeline processing.

    The pipeline is dispatched asynchronously; follow the shipment status for
    progress. Re-uploading is rejected unless the shipment is CREATED/FAILED.
    """
    shipment, artifact = service.upload(shipment_id, file)

    queued = False
    if shipment.status == "CREATED":
        queue_processing(shipment)
        queued = True

    return ArtifactUploadResponse(
        shipment_id=str(shipment.id),
        artifact=ArtifactRead(
            name=artifact.name,
            path=artifact.path,
            size=artifact.size,
            content_type=artifact.content_type,
            sha256=artifact.sha256,
        ),
        queued=queued,
    )


@router.get("/{shipment_id}/artifact")
def download_artifact(
    shipment_id: uuid.UUID,
    service: ArtifactService = Depends(_service),
) -> Response:
    """Download the shipment artifact."""
    shipment, data = service.download(shipment_id)
    if not shipment.artifact_name:
        raise AppError("ARTIFACT_MISSING", "Shipment has no artifact", status_code=404)
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{shipment.artifact_name}"',
            "X-Artifact-SHA256": sha256_of(data),
        },
    )
