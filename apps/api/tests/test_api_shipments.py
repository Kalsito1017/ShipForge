"""API tests for the shipment endpoints."""

import uuid
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.shipment import Shipment
from app.services import state_machine as sm
from tests.conftest import requires_db

pytestmark = requires_db


def _create(
    client: TestClient, product: str = "payment-service", version: str = "2.4.1"
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/shipments",
        json={"product": product, "version": version},
    )
    assert response.status_code == 202, response.text
    return cast(dict[str, Any], response.json())


class TestHealth:
    def test_health(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_ready(self, client: TestClient) -> None:
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestCreateShipment:
    def test_create_returns_202_in_created_state(self, client: TestClient) -> None:
        body = _create(client)
        assert body["status"] == sm.CREATED
        assert body["product"] == "payment-service"
        assert body["version"] == "2.4.1"
        assert body["published_at"] is None

    def test_create_writes_created_event(self, client: TestClient) -> None:
        body = _create(client)
        events = client.get(f"/api/v1/shipments/{body['id']}/events").json()
        assert len(events) == 1
        assert events[0]["event_type"] == sm.CREATED
        assert events[0]["metadata"]["to"] == sm.CREATED

    def test_duplicate_product_version_conflict(self, client: TestClient) -> None:
        _create(client)
        response = client.post(
            "/api/v1/shipments", json={"product": "payment-service", "version": "2.4.1"}
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONFLICT"

    @pytest.mark.parametrize(
        "payload",
        [
            {"version": "1.0.0"},
            {"product": "payment-service"},
            {},
            {"product": "", "version": "1.0.0"},
            {"product": "bad product!", "version": "1.0.0"},
        ],
    )
    def test_invalid_payload_422(self, client: TestClient, payload: dict[str, Any]) -> None:
        response = client.post("/api/v1/shipments", json=payload)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"


class TestGetShipment:
    def test_get_existing(self, client: TestClient) -> None:
        created = _create(client)
        response = client.get(f"/api/v1/shipments/{created['id']}")
        assert response.status_code == 200
        assert response.json()["id"] == created["id"]

    def test_get_missing_404(self, client: TestClient) -> None:
        response = client.get("/api/v1/shipments/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"


class TestListShipments:
    def test_list_pagination_and_filters(self, client: TestClient) -> None:
        _create(client, product="payment-service", version="1.0.0")
        _create(client, product="payment-service", version="1.0.1")
        _create(client, product="auth-service", version="2.0.0")

        response = client.get("/api/v1/shipments")
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 3
        assert body["limit"] == 20
        assert body["offset"] == 0

        filtered = client.get("/api/v1/shipments", params={"product": "payment-service"}).json()
        assert filtered["total"] == 2

        by_status = client.get("/api/v1/shipments", params={"status": sm.CREATED}).json()
        assert by_status["total"] == 3

        paged = client.get("/api/v1/shipments", params={"limit": 1, "offset": 2}).json()
        assert paged["total"] == 3
        assert len(paged["items"]) == 1
        assert paged["offset"] == 2

    def test_limit_capped(self, client: TestClient) -> None:
        response = client.get("/api/v1/shipments", params={"limit": 1000})
        assert response.status_code == 422


class TestEvents:
    def test_events_404_for_missing_shipment(self, client: TestClient) -> None:
        response = client.get("/api/v1/shipments/00000000-0000-0000-0000-000000000000/events")
        assert response.status_code == 404

    def test_events_ordered(self, client: TestClient) -> None:
        created = _create(client)
        events = client.get(f"/api/v1/shipments/{created['id']}/events").json()
        timestamps = [event["created_at"] for event in events]
        assert timestamps == sorted(timestamps)


class TestRetry:
    def _force_failed(self, client: TestClient, db_session: Session) -> dict[str, Any]:
        body = _create(client)
        from app.services import state_machine

        session = db_session
        shipment = session.get(Shipment, uuid.UUID(cast(str, body["id"])))
        assert shipment is not None
        # Walk valid transitions: CREATED -> VALIDATING -> BUILDING -> FAILED.
        state_machine.transition(session, shipment, state_machine.VALIDATING)
        state_machine.transition(session, shipment, state_machine.BUILDING)
        state_machine.transition(
            session,
            shipment,
            state_machine.FAILED,
            error_code="BUILD_FAILED",
            error_message="boom",
        )
        session.commit()
        return body

    def test_retry_moves_failed_to_validating(
        self, client: TestClient, db_session: Session
    ) -> None:
        body = self._force_failed(client, db_session)
        response = client.post(f"/api/v1/shipments/{body['id']}/retry")
        assert response.status_code == 202
        assert response.json()["status"] == sm.VALIDATING

        events = client.get(f"/api/v1/shipments/{body['id']}/events").json()
        assert events[-1]["event_type"] == "RETRY"

    def test_retry_requires_failed_status(self, client: TestClient) -> None:
        created = _create(client)
        response = client.post(f"/api/v1/shipments/{created['id']}/retry")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONFLICT"

    def test_retry_missing_404(self, client: TestClient) -> None:
        response = client.post("/api/v1/shipments/00000000-0000-0000-0000-000000000000/retry")
        assert response.status_code == 404
