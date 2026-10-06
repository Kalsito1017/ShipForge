# syntax=docker/dockerfile:1
# ShipForge API — minimal, non-root, pinned dependencies.

FROM python:3.12-slim AS builder

WORKDIR /build
COPY infrastructure/docker/requirements.lock .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.lock

FROM python:3.12-slim AS runtime

# No root at runtime: dedicated unprivileged user.
RUN groupadd --gid 10001 shipforge \
    && useradd --uid 10001 --gid shipforge --no-create-home --shell /usr/sbin/nologin shipforge

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/srv/apps/api \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=builder /opt/venv /opt/venv
COPY apps/api /srv/apps/api

WORKDIR /srv/apps/api
USER shipforge

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
