"""API v1 router aggregation."""

from fastapi import APIRouter

from app.api.v1 import artifacts, health, shipments

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(shipments.router, prefix="/shipments", tags=["shipments"])
api_router.include_router(artifacts.router, prefix="/shipments", tags=["artifacts"])
