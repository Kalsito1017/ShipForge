"""Test fixtures: database setup and FastAPI test client."""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
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
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def _override() -> Generator[Session, None, None]:
        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
