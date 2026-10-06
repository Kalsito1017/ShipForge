"""API v1 router aggregation."""

from fastapi import APIRouter

from app.api.v1 import analyze, artifacts, auth, health, shipments

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(shipments.router, prefix="/shipments", tags=["shipments"])
api_router.include_router(artifacts.router, prefix="/shipments", tags=["artifacts"])
api_router.include_router(analyze.router, prefix="/shipments", tags=["ai"])
