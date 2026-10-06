"""Artifact business logic: validation, storage, metadata."""

import uuid

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.core.artifacts import (
    archive_integrity_error,
    build_artifact_path,
    new_artifact_id,
    sha256_of,
    validate_artifact_name,
    validate_content_type,
    validate_size,
)
from app.core.config import get_settings
from app.core.exceptions import ARTIFACT_MISSING, AppError, NotFoundError
from app.core.logging import get_logger
from app.core.storage import ArtifactStorage, bytes_reader, get_storage
from app.models.shipment import Shipment, ShipmentEvent, ShipmentLog
from app.repositories.shipment_repository import ShipmentRepository

logger = get_logger(__name__)

# States in which an artifact may be (re)uploaded: before processing or after a
# failed run (user replaces the artifact and retries).
UPLOADABLE_STATUSES = frozenset({"CREATED", "FAILED"})


class ArtifactInfo:
    """Artifact metadata returned to callers."""

    def __init__(self, name: str, path: str, size: int, content_type: str, sha256: str) -> None:
        self.name = name
        self.path = path
        self.size = size
        self.content_type = content_type
        self.sha256 = sha256

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "path": self.path,
            "size": self.size,
            "content_type": self.content_type,
            "sha256": self.sha256,
        }


class ArtifactService:
    """Orchestrates artifact upload/download for a shipment."""

    def __init__(
        self,
        session: Session,
        storage: ArtifactStorage | None = None,
    ) -> None:
        self._session = session
        self._storage = storage if storage is not None else get_storage()
        self._repo = ShipmentRepository(session)
        self._settings = get_settings()

    def upload(self, shipment_id: uuid.UUID, upload: UploadFile) -> tuple[Shipment, ArtifactInfo]:
        """Validate and store the artifact, linking it to the shipment."""
        shipment = self._get_shipment(shipment_id)
        if shipment.status not in UPLOADABLE_STATUSES:
            raise AppError(
                "CONFLICT",
                f"Cannot upload artifacts while shipment is {shipment.status}",
                status_code=409,
            )

        filename = upload.filename or ""
        content_type = upload.content_type or "application/octet-stream"
        validate_artifact_name(filename)
        validate_content_type(content_type)

        data = upload.file.read()
        validate_size(len(data), self._settings.artifact_max_size_mb)

        integrity_error = archive_integrity_error(data, filename)
        if integrity_error is not None:
            raise AppError("VALIDATION_ERROR", integrity_error)

        path = build_artifact_path(shipment.product, shipment.version, filename)
        self._storage.put(path, bytes_reader(data), len(data), content_type)

        artifact = ArtifactInfo(
            name=filename,
            path=path,
            size=len(data),
            content_type=content_type,
            sha256=sha256_of(data),
        )

        shipment.artifact_name = filename
        shipment.artifact_path = path
        self._session.add(
            ShipmentEvent(
                id=new_artifact_id(),
                shipment_id=shipment.id,
                event_type="ARTIFACT_UPLOADED",
                message=f"Artifact {filename} uploaded",
                meta={
                    "path": path,
                    "size": artifact.size,
                    "content_type": content_type,
                    "sha256": artifact.sha256,
                    "artifact_id": str(new_artifact_id()),
                },
            )
        )
        self._session.add(
            ShipmentLog(
                id=new_artifact_id(),
                shipment_id=shipment.id,
                stage="UPLOAD",
                level="INFO",
                message=f"Stored artifact at {path}",
                context={"sha256": artifact.sha256, "size": artifact.size},
            )
        )
        self._session.flush()
        # Commit before dispatching: the worker must see the artifact.
        self._session.commit()
        logger.info(
            "artifact stored",
            extra={
                "shipment_id": str(shipment.id),
                "stage": "UPLOAD",
                "artifact_path": path,
                "artifact_size": artifact.size,
            },
        )
        return shipment, artifact

    def download(self, shipment_id: uuid.UUID) -> tuple[Shipment, bytes]:
        """Return the shipment and its artifact bytes."""
        shipment = self._get_shipment(shipment_id)
        if not shipment.artifact_path:
            raise AppError(ARTIFACT_MISSING, "Shipment has no artifact", status_code=404)
        try:
            data = self._storage.get(shipment.artifact_path)
        except KeyError:
            raise AppError(
                ARTIFACT_MISSING,
                "Artifact is no longer available in storage",
                status_code=404,
            ) from None
        return shipment, data

    def _get_shipment(self, shipment_id: uuid.UUID) -> Shipment:
        shipment = self._repo.get(shipment_id)
        if shipment is None:
            raise NotFoundError("Shipment not found", shipment_id=str(shipment_id))
        return shipment
