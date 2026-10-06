"""Celery application for the ShipForge worker (pipeline stages land in M2)."""

# Explicit registration: autodiscover looks for <pkg>.tasks modules and would
# miss worker_app.tasks.pipeline.
import worker_app.tasks.pipeline  # noqa: E402,F401
from worker_app.celery_app import celery_app

__all__ = ["celery_app"]
