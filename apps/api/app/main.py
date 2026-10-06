"""FastAPI application entry point."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from time import monotonic

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1 import health
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.metrics import observe_request
from app.db.session import dispose_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application startup/shutdown with graceful resource cleanup."""
    settings = get_settings()
    configure_logging(
        service="shipforge-api",
        level=settings.log_level,
        extra_loggers=("uvicorn", "uvicorn.error", "uvicorn.access"),
    )
    yield
    dispose_engine()


def _route_template(request: Request) -> str:
    """Return the matched route template (bounded label cardinality)."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path if path else request.url.path


def _instrument(app: FastAPI) -> None:
    """Record request count and latency for every HTTP request."""

    @app.middleware("http")
    async def _metrics_middleware(
        request: Request, call_next: Callable[[Request], object]
    ) -> Response:
        started = monotonic()
        response: Response = await call_next(request)  # type: ignore[misc]
        elapsed = monotonic() - started
        observe_request(
            method=request.method,
            path=_route_template(request),
            status=response.status_code,
            duration=elapsed,
        )
        return response


def create_app() -> FastAPI:
    """Application factory."""
    app = FastAPI(
        title="ShipForge API",
        description="Repository-based software shipment platform",
        version="0.1.0",
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    _instrument(app)
    app.include_router(api_router, prefix="/api/v1")
    # Health/readiness/metrics also served at root per PLAN.md §9.
    app.include_router(health.router, include_in_schema=False)
    _mount_dashboard(app)
    return app


def _mount_dashboard(app: FastAPI) -> None:
    """Serve the shipment dashboard at / (static assets at /static)."""
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(static_dir / "index.html")


app = create_app()
