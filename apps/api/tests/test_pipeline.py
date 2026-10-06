"""Pipeline tests: stages, failure simulation, resume and idempotency."""

import io
import tarfile
import uuid
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.core.storage import InMemoryStorage
from app.models.shipment import Shipment, ShipmentEvent
from app.services import state_machine as sm
from app.services.shipment import ShipmentService
from tests.conftest import requires_db
from worker_app.services.pipeline import PipelineRunner

pytestmark = requires_db


def _make_tarball() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name in ("main.py", "requirements.txt"):
            info = tarfile.TarInfo(name=name)
            payload = b"# content\n"
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def _seed(
    db_session: Session, storage: InMemoryStorage, product: str, version: str = "1.0.0"
) -> Shipment:
    """Create a shipment with an artifact stored, ready for processing."""
    service = ShipmentService(db_session)
    shipment = service.create_shipment(product=product, version=version, artifact_name=None)
    data = _make_tarball()
    path = f"artifacts/{product}/{version}/{product}-{version}.tar.gz"
    storage.put(path, io.BytesIO(data), len(data), "application/gzip")
    shipment.artifact_name = f"{product}-{version}.tar.gz"
    shipment.artifact_path = path
    db_session.commit()
    return shipment


def _run(
    db_session: Session, storage: InMemoryStorage, shipment_id: uuid.UUID
) -> dict[str, Any]:
    runner = PipelineRunner(db_session, storage)
    return runner.run(shipment_id)


class TestHappyPath:
    def test_full_pipeline_publishes_once(
        self, db_session: Session, storage: InMemoryStorage
    ) -> None:
        shipment = _seed(db_session, storage, "payment-service")
        result = _run(db_session, storage, shipment.id)

        assert result["outcome"] == "published"
        assert [s["stage"] for s in result["stages"]] == [
            "VALIDATING",
            "BUILDING",
            "SCANNING",
            "PUBLISHING",
        ]
        assert all(s["ok"] for s in result["stages"])

        db_session.refresh(shipment)
        assert shipment.status == sm.PUBLISHED
        assert shipment.published_at is not None

    def test_event_trail_records_every_transition(
        self, db_session: Session, storage: InMemoryStorage
    ) -> None:
        shipment = _seed(db_session, storage, "auth-service")
        _run(db_session, storage, shipment.id)

        events = db_session.query(ShipmentEvent).filter_by(shipment_id=shipment.id).all()
        statuses = {e.meta["to"] for e in events if e.meta and "to" in e.meta}
        assert statuses == {
            sm.CREATED,
            sm.VALIDATING,
            sm.BUILDING,
            sm.SCANNING,
            sm.READY,
            sm.PUBLISHED,
        }


class TestIdempotency:
    def test_rerun_after_publish_is_noop(
        self, db_session: Session, storage: InMemoryStorage
    ) -> None:
        shipment = _seed(db_session, storage, "payment-service")
        first = _run(db_session, storage, shipment.id)
        assert first["outcome"] == "published"

        second = _run(db_session, storage, shipment.id)
        assert second["outcome"] == "already_published"

        # No duplicate publish events (PLAN.md §15).
        events = (
            db_session.query(ShipmentEvent).filter_by(shipment_id=shipment.id).all()
        )
        publish_events = [e for e in events if e.event_type == "PUBLISHED"]
        assert len(publish_events) == 1

    def test_duplicate_delivery_cannot_double_publish(
        self, db_session: Session, storage: InMemoryStorage
    ) -> None:
        """A retried Celery delivery must not create a second publication."""
        shipment = _seed(db_session, storage, "payment-service")
        _run(db_session, storage, shipment.id)
        # Simulate redelivery of the same task.
        _run(db_session, storage, shipment.id)
        _run(db_session, storage, shipment.id)

        db_session.refresh(shipment)
        assert shipment.status == sm.PUBLISHED
        events = (
            db_session.query(ShipmentEvent).filter_by(shipment_id=shipment.id).all()
        )
        assert len([e for e in events if e.event_type == "PUBLISHED"]) == 1

    def test_awaiting_artifact_is_noop(self, db_session: Session) -> None:
        service = ShipmentService(db_session)
        shipment = service.create_shipment(
            product="late-upload", version="1.0.0", artifact_name=None
        )
        db_session.commit()

        result = _run(db_session, InMemoryStorage(), shipment.id)
        assert result["outcome"] == "awaiting_artifact"

        db_session.refresh(shipment)
        assert shipment.status == sm.CREATED


class TestResume:
    def test_resumes_from_current_stage(
        self, db_session: Session, storage: InMemoryStorage
    ) -> None:
        """A crash mid-pipeline resumes at the right stage on redelivery."""
        shipment = _seed(db_session, storage, "payment-service")
        # Walk to BUILDING as if the worker died after validation.
        sm.transition(db_session, shipment, sm.VALIDATING)
        sm.transition(db_session, shipment, sm.BUILDING)
        db_session.commit()

        result = _run(db_session, storage, shipment.id)
        assert result["outcome"] == "published"
        # VALIDATING was skipped — resume semantics.
        assert [s["stage"] for s in result["stages"]] == ["BUILDING", "SCANNING", "PUBLISHING"]


class TestFailureSimulation:
    @pytest.mark.parametrize(
        ("product", "stage", "error_code"),
        [
            ("failure-validation", "VALIDATING", "VALIDATION_ERROR"),
            ("failure-build", "BUILDING", "BUILD_FAILED"),
            ("failure-scan", "SCANNING", "SCAN_FAILED"),
            ("failure-timeout", "VALIDATING", "TIMEOUT"),
        ],
    )
    def test_failure_products(
        self,
        db_session: Session,
        storage: InMemoryStorage,
        product: str,
        stage: str,
        error_code: str,
    ) -> None:
        shipment = _seed(db_session, storage, product)
        result = _run(db_session, storage, shipment.id)

        assert result["outcome"] == "failed"
        assert result["stage"] == stage
        assert result["error_code"] == error_code

        db_session.refresh(shipment)
        assert shipment.status == sm.FAILED
        assert shipment.error_code == error_code
        assert shipment.error_message

    def test_failed_shipment_can_be_retried(
        self, db_session: Session, storage: InMemoryStorage
    ) -> None:
        """FAIL -> retry -> replace product -> success (demo scenario §38)."""
        shipment = _seed(db_session, storage, "failure-build")
        assert _run(db_session, storage, shipment.id)["outcome"] == "failed"

        # Retry: FAILED -> VALIDATING, then the pipeline succeeds. The failure
        # product still fails build — so simulate the "fix" by renaming product.
        shipment.product = "payment-service"
        service = ShipmentService(db_session)
        service.retry_shipment(shipment.id)
        db_session.commit()

        result = _run(db_session, storage, shipment.id)
        assert result["outcome"] == "published"

        db_session.refresh(shipment)
        assert shipment.status == sm.PUBLISHED

    def test_missing_artifact_fails_validation(
        self, db_session: Session, storage: InMemoryStorage
    ) -> None:
        service = ShipmentService(db_session)
        shipment = service.create_shipment(product="ghost", version="1.0.0", artifact_name=None)
        # Artifact metadata set, but nothing actually in storage.
        shipment.artifact_name = "ghost-1.0.0.tar.gz"
        shipment.artifact_path = "artifacts/ghost/1.0.0/ghost-1.0.0.tar.gz"
        db_session.commit()

        result = _run(db_session, storage, shipment.id)
        assert result["outcome"] == "failed"
        assert result["error_code"] == "ARTIFACT_MISSING"
