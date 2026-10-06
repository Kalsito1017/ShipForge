# ruff: noqa: I001  # worker_app.multiproc MUST be imported first (sets
# PROMETHEUS_MULTIPROC_DIR before app.core.metrics creates metric objects).
"""Celery application entrypoint for the ShipForge worker."""

import sys

import worker_app.multiproc

from worker_app.celery_app import celery_app

# The real worker (and only the real worker) owns the metrics directory and
# observability servers. Auxiliary commands like `celery inspect ping` (used
# by healthchecks) import this module too — they must stay side-effect free,
# otherwise every healthcheck wipes or pollutes live metrics.
#
# Ordering matters: the wipe must run BEFORE anything imports app.core.metrics
# (metric objects bind to per-pid files at creation time).
if "worker" in sys.argv and "inspect" not in sys.argv:
    worker_app.multiproc.configure_multiprocess(wipe=True)

    # Task registration must happen at import time so Celery sees the tasks.
    import worker_app.tasks.pipeline
    from worker_app.tasks.pipeline import start_observability

    start_observability()

__all__ = ["celery_app"]
