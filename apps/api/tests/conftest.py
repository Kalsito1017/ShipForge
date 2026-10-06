"""Test fixtures: database setup and FastAPI test client."""

from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.storage import InMemoryStorage
from app.db.base import Base
from app.db.session import get_db
from app.main import app

# Import models so metadata is complete.
from app.models import Shipment, ShipmentEvent, ShipmentLog, User  # noqa: F401

TEST_JWT_SECRET = "test-secret-not-for-production"
TEST_DB_NAME = "shipment_test"
TEST_USERS = (
    ("dev", "dev-pass", "developer"),
    ("rm", "rm-pass", "release_manager"),
    ("admin", "admin-pass", "admin"),
)


def _test_database_url() -> str:
    """Point at a dedicated test database — never the dev/CI data."""
    base = get_settings().database_url
    return base.rsplit("/", 1)[0] + f"/{TEST_DB_NAME}"


def _ensure_test_database() -> bool:
    """Create the test database if missing. Returns True when available."""
    from sqlalchemy import create_engine as _create_engine

    server_url = get_settings().database_url.rsplit("/", 1)[0] + "/postgres"
    try:
        server = _create_engine(server_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
        with server.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": TEST_DB_NAME},
            ).first()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
        server.dispose()
        return True
    except OperationalError:
        return False


def _database_available() -> bool:
    return _ensure_test_database()


requires_db = pytest.mark.skipif(
    not _database_available(),
    reason="PostgreSQL is not reachable; start it with `docker compose up -d postgres`",
)


@pytest.fixture(scope="session")
def engine() -> Generator[Engine, None, None]:
    """Create tables in the dedicated test database.

    The dev/CI database is never touched: tests and the live stack can run
    concurrently without interfering.
    """
    eng = create_engine(_test_database_url(), pool_pre_ping=True)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def db_session(engine: Engine) -> Generator[Session, None, None]:
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        # Keep the DB clean between tests.
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
        session.close()


@pytest.fixture()
def storage() -> InMemoryStorage:
    """In-memory artifact storage for tests (no MinIO required)."""
    return InMemoryStorage()


@pytest.fixture(autouse=True)
def queued_tasks(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Record task dispatches instead of hitting a real Celery broker.

    Autouse: no test may ever reach the live queue — a stray dispatch would
    let the real worker mutate test state.
    """
    calls: list[Any] = []

    def _fake_dispatch(shipment_id: Any) -> str:
        calls.append(shipment_id)
        return "test-task-id"

    monkeypatch.setattr("app.core.queue.queue_processing", _fake_dispatch)
    return calls


@pytest.fixture(autouse=True)
def auth_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Point JWT signing at a known test secret."""
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def seed_users(db_session: Session) -> dict[str, dict[str, str]]:
    """Insert one user per role; returns {role: {username, password, token}}."""
    from app.core.auth import create_access_token, hash_password

    result: dict[str, dict[str, str]] = {}
    for username, password, role in TEST_USERS:
        user = User(
            username=username,
            password_hash=hash_password(password),
            role=role,
        )
        db_session.add(user)
        db_session.flush()
        token = create_access_token(user.id, user.username, user.role)
        result[role] = {"username": username, "password": password, "token": token}
    db_session.commit()
    return result


def _client_with_token(token: str, db_session: Session, storage: InMemoryStorage) -> TestClient:
    def _override() -> Generator[Session, None, None]:
        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise

    app.dependency_overrides[get_db] = _override
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture()
def admin_client(
    db_session: Session,
    queued_tasks: list[Any],
    storage: InMemoryStorage,
    seed_users: dict[str, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient, None, None]:
    """Test client authenticated as admin (all permissions)."""
    monkeypatch.setattr("app.services.artifact.get_storage", lambda: storage)
    with _client_with_token(seed_users["admin"]["token"], db_session, storage) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def dev_client(
    db_session: Session,
    queued_tasks: list[Any],
    storage: InMemoryStorage,
    seed_users: dict[str, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient, None, None]:
    """Test client authenticated as developer (no retry/publish)."""
    monkeypatch.setattr("app.services.artifact.get_storage", lambda: storage)
    with _client_with_token(seed_users["developer"]["token"], db_session, storage) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def rm_client(
    db_session: Session,
    queued_tasks: list[Any],
    storage: InMemoryStorage,
    seed_users: dict[str, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient, None, None]:
    """Test client authenticated as release_manager (retry/publish allowed)."""
    monkeypatch.setattr("app.services.artifact.get_storage", lambda: storage)
    with _client_with_token(seed_users["release_manager"]["token"], db_session, storage) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def client(admin_client: TestClient) -> Generator[TestClient, None, None]:
    """Default client: authenticated as admin for backwards compatibility."""
    yield admin_client
