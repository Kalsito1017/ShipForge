"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1 import health
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.db.session import dispose_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application startup/shutdown with graceful resource cleanup."""
    settings = get_settings()
    configure_logging(service="shipforge-api", level=settings.log_level)
    yield
    dispose_engine()


def create_app() -> FastAPI:
    """Application factory."""
    app = FastAPI(
        title="ShipForge API",
        description="Repository-based software shipment platform",
        version="0.1.0",
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    app.include_router(api_router, prefix="/api/v1")
    # Health/readiness also served at root per PLAN.md §9.
    app.include_router(health.router, include_in_schema=False)
    return app


app = create_app()
