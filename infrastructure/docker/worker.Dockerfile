# syntax=docker/dockerfile:1
# ShipForge Worker — minimal, non-root, pinned dependencies.
#
# Installs both app packages: the worker imports the shared domain modules
# (models, state machine, storage) from shipforge-api.

FROM python:3.12-slim AS builder

WORKDIR /build
COPY infrastructure/docker/requirements.lock .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.lock

FROM python:3.12-slim AS runtime

RUN groupadd --gid 10001 shipforge \
    && useradd --uid 10001 --gid shipforge --no-create-home --shell /usr/sbin/nologin shipforge

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/srv/apps/api:/srv/apps/worker \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=builder /opt/venv /opt/venv
COPY apps/api /srv/apps/api
COPY apps/worker /srv/apps/worker

WORKDIR /srv/apps/worker
USER shipforge

HEALTHCHECK --interval=15s --timeout=10s --start-period=15s --retries=3 \
    CMD ["celery", "-A", "worker_app.main.celery_app", "inspect", "ping", "--timeout", "5"]

CMD ["celery", "-A", "worker_app.main.celery_app", "worker", "--loglevel=INFO", "--concurrency=2"]
