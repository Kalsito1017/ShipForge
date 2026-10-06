"""Tests for JWT auth, role permissions and the AI incident assistant."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.auth import (
    ROLE_PERMISSIONS,
    create_access_token,
    hash_password,
    verify_password,
)
from app.core.config import get_settings
from app.services.ai import IncidentAnalyzer
from tests.conftest import requires_db

pytestmark = requires_db


class TestPasswordHashing:
    def test_roundtrip(self) -> None:
        pw_hash = hash_password("s3cret")
        assert pw_hash != "s3cret"
        assert verify_password("s3cret", pw_hash)
        assert not verify_password("wrong", pw_hash)

    def test_unique_salts(self) -> None:
        assert hash_password("same") != hash_password("same")

    def test_invalid_hash_returns_false(self) -> None:
        assert not verify_password("x", "not-a-bcrypt-hash")


class TestTokens:
    def test_create_and_decode(self) -> None:
        import jwt

        token = create_access_token(uuid.uuid4(), "alice", "developer")
        payload = jwt.decode(
            token, get_settings().jwt_secret, algorithms=[get_settings().jwt_algorithm]
        )
        assert payload["username"] == "alice"
        assert payload["role"] == "developer"

    def test_expired_token_rejected(self, client: TestClient) -> None:
        import time

        import jwt as pyjwt

        settings = get_settings()
        expired = pyjwt.encode(
            {"sub": str(uuid.uuid4()), "exp": int(time.time()) - 60},
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )
        headers = {"Authorization": f"Bearer {expired}"}
        response = client.get("/api/v1/auth/me", headers=headers)
        assert response.status_code == 401

    def test_tampered_token_rejected(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer not.a.token"}
        )
        assert response.status_code == 401


class TestRoleMatrix:
    """PLAN.md §27 permissions per role."""

    def test_me_returns_profile(self, dev_client: TestClient) -> None:
        response = dev_client.get("/api/v1/auth/me")
        assert response.status_code == 200
        body = response.json()
        assert body["username"] == "dev"
        assert body["role"] == "developer"

    def test_login_flow(
        self, client: TestClient, seed_users: dict[str, dict[str, str]]
    ) -> None:
        creds = seed_users["developer"]
        response = client.post(
            "/api/v1/auth/login",
            json={"username": creds["username"], "password": creds["password"]},
        )
        assert response.status_code == 200
        assert response.json()["token_type"] == "bearer"
        assert response.json()["access_token"]

    def test_login_wrong_password(
        self, client: TestClient, seed_users: dict[str, dict[str, str]]
    ) -> None:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": seed_users["developer"]["username"], "password": "nope"},
        )
        assert response.status_code == 401

    def test_login_unknown_user(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/login", json={"username": "ghost", "password": "x"}
        )
        assert response.status_code == 401

    def test_unauthenticated_rejected(self) -> None:
        from fastapi.testclient import TestClient as TC

        from app.main import app

        anonymous = TC(app)
        response = anonymous.get("/api/v1/shipments")
        assert response.status_code == 401

    def test_developer_can_read_and_create(self, dev_client: TestClient) -> None:
        assert dev_client.get("/api/v1/shipments").status_code == 200
        created = dev_client.post(
            "/api/v1/shipments", json={"product": "dev-can", "version": "1.0.0"}
        )
        assert created.status_code == 202

    def test_developer_cannot_retry_or_publish(self, dev_client: TestClient) -> None:
        created = dev_client.post(
            "/api/v1/shipments", json={"product": "dev-denied", "version": "1.0.0"}
        )
        sid = created.json()["id"]
        assert dev_client.post(f"/api/v1/shipments/{sid}/retry").status_code == 403
        assert dev_client.post(f"/api/v1/shipments/{sid}/publish").status_code == 403

    def test_release_manager_can_retry(self, rm_client: TestClient) -> None:
        created = rm_client.post(
            "/api/v1/shipments", json={"product": "rm-can", "version": "1.0.0"}
        )
        sid = created.json()["id"]
        # Not FAILED -> 409 means permission passed (not 403).
        assert rm_client.post(f"/api/v1/shipments/{sid}/retry").status_code == 409

    def test_admin_can_publish(self, admin_client: TestClient) -> None:
        created = admin_client.post(
            "/api/v1/shipments", json={"product": "admin-can", "version": "1.0.0"}
        )
        sid = created.json()["id"]
        # Not READY -> 409 means permission passed.
        assert admin_client.post(f"/api/v1/shipments/{sid}/publish").status_code == 409

    def test_permission_table_matches_plan(self) -> None:
        assert "shipment:retry" not in ROLE_PERMISSIONS["developer"]
        assert "shipment:retry" in ROLE_PERMISSIONS["release_manager"]
        assert "shipment:publish" in ROLE_PERMISSIONS["release_manager"]
        assert "user:manage" in ROLE_PERMISSIONS["admin"]
        assert "user:manage" not in ROLE_PERMISSIONS["release_manager"]


class TestIncidentAnalysis:
    def _failed_shipment(self, db_session: Session) -> uuid.UUID:
        from app.services import state_machine as sm
        from app.services.shipment import ShipmentService

        service = ShipmentService(db_session)
        shipment = service.create_shipment(
            product="ai-case", version="1.0.0", artifact_name=None
        )
        sm.transition(db_session, shipment, sm.VALIDATING)
        sm.transition(db_session, shipment, sm.BUILDING)
        sm.transition(
            db_session,
            shipment,
            sm.FAILED,
            error_code="DEPENDENCY_ERROR",
            error_message="Could not resolve package foo==9.9.9",
        )
        db_session.commit()
        return shipment.id

    def test_mock_analysis_for_dependency_error(self, db_session: Session) -> None:
        sid = self._failed_shipment(db_session)
        result = IncidentAnalyzer(db_session).analyze(sid)
        assert result.source == "mock"
        assert result.advisory is True
        assert result.analysis.category == "DEPENDENCY"
        assert result.analysis.confidence > 0.5
        assert result.analysis.severity in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        assert len(result.analysis.recommendations) >= 1

    def test_analysis_via_api(self, dev_client: TestClient, db_session: Session) -> None:
        sid = self._failed_shipment(db_session)
        response = dev_client.post(f"/api/v1/shipments/{sid}/analyze")
        assert response.status_code == 200
        body = response.json()
        assert body["advisory"] is True
        assert body["analysis"]["category"] == "DEPENDENCY"
        assert body["source"] == "mock"

    def test_analysis_unknown_shipment_404(self, dev_client: TestClient) -> None:
        response = dev_client.post(f"/api/v1/shipments/{uuid.uuid4()}/analyze")
        assert response.status_code == 404

    def test_published_shipment_is_no_incident(self, db_session: Session) -> None:
        from app.services import state_machine as sm
        from app.services.shipment import ShipmentService

        service = ShipmentService(db_session)
        shipment = service.create_shipment(
            product="ok-case", version="1.0.0", artifact_name=None
        )
        for target in (sm.VALIDATING, sm.BUILDING, sm.SCANNING, sm.READY, sm.PUBLISHED):
            sm.transition(db_session, shipment, target)
        db_session.commit()

        result = IncidentAnalyzer(db_session).analyze(shipment.id)
        assert result.analysis.severity == "LOW"
        assert "successfully" in result.analysis.root_cause

    def test_mock_covers_all_error_codes(self) -> None:
        """Every stable error code gets a deterministic diagnosis."""
        from app.services.ai import _MOCK_RULES

        codes = {rule[0] for rule in _MOCK_RULES}
        for code in (
            "DEPENDENCY_ERROR",
            "ARTIFACT_MISSING",
            "VALIDATION_ERROR",
            "BUILD_FAILED",
            "SCAN_FAILED",
            "TIMEOUT",
        ):
            assert code in codes
