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
from app.models import Shipment, ShipmentEvent, ShipmentLog  # noqa: F401


def _database_available() -> bool:
    try:
        engine = create_engine(get_settings().database_url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except OperationalError:
        return False


requires_db = pytest.mark.skipif(
    not _database_available(),
    reason="PostgreSQL is not reachable; start it with `docker compose up -d postgres`",
)


@pytest.fixture(scope="session")
def engine() -> Generator[Engine, None, None]:
    """Create tables if missing. The schema is migration-managed (alembic);
    tests never drop it — they only clean rows between tests."""
    eng = create_engine(get_settings().database_url, pool_pre_ping=True)
    Base.metadata.create_all(eng)
    yield eng
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


@pytest.fixture()
def queued_tasks(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Record task dispatches instead of hitting a real Celery broker."""
    calls: list[Any] = []

    def _fake_dispatch(shipment_id: Any) -> str:
        calls.append(shipment_id)
        return "test-task-id"

    monkeypatch.setattr("app.core.queue.queue_processing", _fake_dispatch)
    return calls


@pytest.fixture()
def client(
    db_session: Session,
    queued_tasks: list[Any],
    storage: InMemoryStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[TestClient, None, None]:
    def _override() -> Generator[Session, None, None]:
        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise

    # Tests never touch MinIO: artifact endpoints use in-memory storage.
    monkeypatch.setattr("app.services.artifact.get_storage", lambda: storage)

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
