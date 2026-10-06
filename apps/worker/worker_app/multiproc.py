"""Prometheus multiprocess bootstrap for the Celery worker.

Celery's prefork pool runs tasks in forked children; counters incremented
there would never reach a registry served by the parent process. Prometheus
multiprocess mode writes values to shared memory files which the parent
aggregates at scrape time.

IMPORTANT: this module must be imported BEFORE anything that imports
``app.core.metrics`` — the multiprocess value class is chosen when metric
objects are created.

NOTE: nothing here wipes the directory on import. Wiping is explicit
(``configure_multiprocess(wipe=True)``) and happens exactly once at real
worker startup — see ``worker_app.main``. Wiping at import would let any
auxiliary process (e.g. a healthcheck) destroy live metrics.
"""

import os
import shutil
from pathlib import Path

DEFAULT_DIR = "/tmp/prometheus-multiproc"


def configure_multiprocess(directory: str = DEFAULT_DIR, *, wipe: bool = False) -> str:
    """Set PROMETHEUS_MULTIPROC_DIR, optionally clearing stale files first."""
    path = Path(directory)
    if wipe and path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    os.environ["PROMETHEUS_MULTIPROC_DIR"] = str(path)
    return str(path)


# Side effect on import: ensure the env var is set before metric objects are
# created. No directory mutation here — see module docstring.
configure_multiprocess()
