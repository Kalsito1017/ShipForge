"""API tests for artifact upload/download (PLAN.md §13)."""

import io
import tarfile
import uuid
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.storage import InMemoryStorage
from app.services import state_machine as sm
from tests.conftest import requires_db

pytestmark = requires_db


def _make_tarball() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        info = tarfile.TarInfo(name="main.py")
        payload = b"print('hello shipment')\n"
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def _create_shipment(
    client: TestClient, product: str = "payment-service", version: str = "2.4.1"
) -> dict[str, Any]:
    response = client.post("/api/v1/shipments", json={"product": product, "version": version})
    assert response.status_code == 202, response.text
    return cast(dict[str, Any], response.json())


def _force_status(db_session: Session, shipment_id: str, status: str) -> None:
    """Move a shipment to an arbitrary status via the state machine walk.

    Uses the test session so it operates on the test database.
    """
    from app.models.shipment import Shipment

    shipment = db_session.get(Shipment, uuid.UUID(shipment_id))
    assert shipment is not None
    walk = {
        sm.VALIDATING: [sm.VALIDATING],
        sm.BUILDING: [sm.VALIDATING, sm.BUILDING],
        sm.SCANNING: [sm.VALIDATING, sm.BUILDING, sm.SCANNING],
        sm.READY: [sm.VALIDATING, sm.BUILDING, sm.SCANNING, sm.READY],
        sm.FAILED: [sm.VALIDATING, sm.BUILDING, sm.FAILED],
        sm.PUBLISHED: [sm.VALIDATING, sm.BUILDING, sm.SCANNING, sm.READY, sm.PUBLISHED],
    }[status]
    for step in walk:
        sm.transition(db_session, shipment, step)
    db_session.commit()


class TestUpload:
    def test_upload_stores_artifact_and_queues(
        self, client: TestClient, storage: InMemoryStorage, queued_tasks: list[Any]
    ) -> None:
        body = _create_shipment(client)
        response = client.post(
            f"/api/v1/shipments/{body['id']}/artifact",
            files={"file": ("payment-service-2.4.1.tar.gz", _make_tarball(), "application/gzip")},
        )
        assert response.status_code == 202, response.text
        payload = response.json()
        assert payload["artifact"]["name"] == "payment-service-2.4.1.tar.gz"
        assert payload["artifact"]["path"] == (
            "artifacts/payment-service/2.4.1/payment-service-2.4.1.tar.gz"
        )
        assert payload["artifact"]["size"] > 0
        assert len(payload["artifact"]["sha256"]) == 64
        assert payload["queued"] is True

        events = client.get(f"/api/v1/shipments/{body['id']}/events").json()
        assert any(event["event_type"] == "ARTIFACT_UPLOADED" for event in events)

    def test_upload_invalid_filename_400(self, client: TestClient) -> None:
        body = _create_shipment(client)
        response = client.post(
            f"/api/v1/shipments/{body['id']}/artifact",
            files={"file": ("../evil.tar.gz", _make_tarball(), "application/gzip")},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "ARTIFACT_INVALID_TYPE"

    def test_upload_invalid_content_type_400(self, client: TestClient) -> None:
        body = _create_shipment(client)
        response = client.post(
            f"/api/v1/shipments/{body['id']}/artifact",
            files={"file": ("app.tar.gz", b"x", "text/html")},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "ARTIFACT_INVALID_TYPE"

    def test_upload_corrupt_archive_400(self, client: TestClient) -> None:
        body = _create_shipment(client)
        response = client.post(
            f"/api/v1/shipments/{body['id']}/artifact",
            files={"file": ("broken.tar.gz", b"not a tarball", "application/gzip")},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_upload_too_large_400(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ARTIFACT_MAX_SIZE_MB", "0")
        from app.core.config import get_settings

        get_settings.cache_clear()
        try:
            body = _create_shipment(client)
            response = client.post(
                f"/api/v1/shipments/{body['id']}/artifact",
                files={"file": ("big.tar.gz", _make_tarball() * 3, "application/gzip")},
            )
            assert response.status_code == 400
            assert response.json()["error"]["code"] == "ARTIFACT_TOO_LARGE"
        finally:
            monkeypatch.delenv("ARTIFACT_MAX_SIZE_MB")
            get_settings.cache_clear()

    def test_upload_missing_shipment_404(self, client: TestClient) -> None:
        response = client.post(
            f"/api/v1/shipments/{uuid.uuid4()}/artifact",
            files={"file": ("a.tar.gz", _make_tarball(), "application/gzip")},
        )
        assert response.status_code == 404

    def test_upload_rejected_while_building(
        self, client: TestClient, db_session: Session
    ) -> None:
        body = _create_shipment(client)
        _force_status(db_session, body["id"], sm.BUILDING)
        response = client.post(
            f"/api/v1/shipments/{body['id']}/artifact",
            files={"file": ("a.tar.gz", _make_tarball(), "application/gzip")},
        )
        assert response.status_code == 409


class TestDownload:
    def test_download_roundtrip(self, client: TestClient) -> None:
        body = _create_shipment(client)
        upload = client.post(
            f"/api/v1/shipments/{body['id']}/artifact",
            files={"file": ("payment-service-2.4.1.tar.gz", _make_tarball(), "application/gzip")},
        )
        assert upload.status_code == 202

        response = client.get(f"/api/v1/shipments/{body['id']}/artifact")
        assert response.status_code == 200
        assert response.content.startswith(b"\x1f\x8b")  # gzip magic
        assert "payment-service-2.4.1.tar.gz" in response.headers["content-disposition"]

    def test_download_without_artifact_404(self, client: TestClient) -> None:
        body = _create_shipment(client)
        response = client.get(f"/api/v1/shipments/{body['id']}/artifact")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "ARTIFACT_MISSING"

    def test_download_missing_shipment_404(self, client: TestClient) -> None:
        response = client.get(f"/api/v1/shipments/{uuid.uuid4()}/artifact")
        assert response.status_code == 404


class TestPublishEndpoint:
    def test_publish_requires_ready(self, client: TestClient) -> None:
        body = _create_shipment(client)
        response = client.post(f"/api/v1/shipments/{body['id']}/publish")
        assert response.status_code == 409

    def test_publish_ready_then_idempotent(
        self, client: TestClient, db_session: Session
    ) -> None:
        body = _create_shipment(client)
        _force_status(db_session, body["id"], sm.READY)

        first = client.post(f"/api/v1/shipments/{body['id']}/publish")
        assert first.status_code == 200
        assert first.json()["status"] == sm.PUBLISHED
        assert first.json()["published_at"] is not None

        # Idempotent: publishing again is a safe no-op (PLAN.md §15).
        second = client.post(f"/api/v1/shipments/{body['id']}/publish")
        assert second.status_code == 200
        assert second.json()["status"] == sm.PUBLISHED

        events = client.get(f"/api/v1/shipments/{body['id']}/events").json()
        publish_events = [e for e in events if e["event_type"] == "PUBLISHED"]
        assert len(publish_events) == 1
