"""Health, readiness and Prometheus metrics endpoints."""

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.metrics import render_metrics
from app.db.session import get_engine

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness: the process is up."""
    return {"status": "ok"}


@router.get("/ready")
def ready(response: Response) -> dict[str, str]:
    """Readiness: the database is reachable."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable"}
    return {"status": "ok"}


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    """Prometheus metrics exposition."""
    payload, content_type = render_metrics()
    return Response(content=payload, media_type=content_type)
