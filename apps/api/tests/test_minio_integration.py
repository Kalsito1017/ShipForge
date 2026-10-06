"""Integration tests against a real MinIO instance (PLAN.md §17).

Skipped automatically when MinIO is unreachable; start it with
`docker compose up -d minio`.
"""

import io
import uuid

import pytest
from sqlalchemy.orm import Session

from app.core.storage import InMemoryStorage, MinioStorage
from app.services import state_machine as sm
from app.services.shipment import ShipmentService
from tests.conftest import requires_db
from tests.test_pipeline import _make_tarball
from worker_app.services.pipeline import PipelineRunner


def _minio_available() -> bool:
    try:
        MinioStorage()
        return True
    except Exception:
        return False


requires_minio = pytest.mark.skipif(
    not _minio_available(),
    reason="MinIO is not reachable; start it with `docker compose up -d minio`",
)


@requires_minio
@requires_db
class TestMinioPipeline:
    def test_upload_validate_publish_with_real_storage(self, db_session: Session) -> None:
        """Full pipeline over MinIO: worker validates and publishes real objects."""
        storage = MinioStorage()
        service = ShipmentService(db_session)

        product = f"minio-it-{uuid.uuid4().hex[:6]}"
        shipment = service.create_shipment(
            product=product, version="1.0.0", artifact_name=None
        )
        data = _make_tarball()
        path = f"artifacts/{product}/1.0.0/{product}-1.0.0.tar.gz"
        storage.put(path, io.BytesIO(data), len(data), "application/gzip")
        shipment.artifact_name = f"{product}-1.0.0.tar.gz"
        shipment.artifact_path = path
        db_session.commit()

        assert storage.exists(path)

        result = PipelineRunner(db_session, storage).run(shipment.id)
        assert result["outcome"] == "published"

        db_session.refresh(shipment)
        assert shipment.status == sm.PUBLISHED

        # Object is still retrievable from MinIO after the run.
        assert storage.get(path) == data

    def test_missing_object_fails_validation(self, db_session: Session) -> None:
        """Worker + MinIO: a vanished artifact fails with ARTIFACT_MISSING."""
        storage = MinioStorage()
        service = ShipmentService(db_session)

        product = f"minio-ghost-{uuid.uuid4().hex[:6]}"
        shipment = service.create_shipment(
            product=product, version="1.0.0", artifact_name=None
        )
        shipment.artifact_name = f"{product}-1.0.0.tar.gz"
        shipment.artifact_path = f"artifacts/{product}/1.0.0/{product}-1.0.0.tar.gz"
        db_session.commit()

        result = PipelineRunner(db_session, storage).run(shipment.id)
        assert result["outcome"] == "failed"
        assert result["error_code"] == "ARTIFACT_MISSING"

    def test_inmemory_backend_is_isolated(self) -> None:
        """Storage backends are interchangeable (unit-level contract check)."""
        memory = InMemoryStorage()
        memory.put("artifacts/x/1.0.0/x.tar.gz", io.BytesIO(b"data"), 4, "application/gzip")
        assert memory.exists("artifacts/x/1.0.0/x.tar.gz")
        assert memory.get("artifacts/x/1.0.0/x.tar.gz") == b"data"
        assert not memory.exists("artifacts/missing")
        with pytest.raises(KeyError):
            memory.get("artifacts/missing")
