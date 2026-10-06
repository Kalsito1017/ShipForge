# Development Guide

## Prerequisites

| Tool | Notes |
|---|---|
| Python 3.12+ | Images pin 3.12; tests run in the local venv |
| Docker + Compose | Development stack |
| make | All workflows are make targets |
| git | Version control |
| kubectl, kind, Helm | Only for the Kubernetes environment |

## First run

```bash
cp .env.example .env      # fill JWT_SECRET (openssl rand -hex 32)
make install              # create .venv, install api + worker (dev extras)
make dev                  # start postgres, redis, minio, api, worker
make migrate              # apply database migrations (seeds dev users)
```

API: `http://localhost:8000` — OpenAPI docs at `/docs`.

Smoke test (login + full pipeline + failure + retry + AI analyze):

```bash
python3 scripts/smoke_compose.py
```

## Make targets

```text
make install        Install dependencies into .venv
make test           Run the test suite (uses the shipment_test database)
make lint           Ruff
make format         Ruff format
make typecheck      Strict mypy
make dev            Start the development stack
make dev-down       Stop it
make build          Build the Docker images
make cluster        Create the kind cluster (builds + loads images + ingress)
make cluster-delete Delete the kind cluster
make deploy         Helm upgrade --install with values-local.yaml
make undeploy       Helm uninstall
make manifests      Render raw Kubernetes manifests from the chart
make logs           Tail compose logs
make status         Compose + kubectl status
make migrate        alembic upgrade head
make migration m="..."   Create a new migration
make clean          Remove caches
```

## Project layout

```text
apps/api/app/
├── api/v1/          Routers (shipments, artifacts, auth, analyze, health)
├── core/            config, logging, exceptions, auth, metrics, storage, queue
├── db/              engine, session, declarative base
├── models/          SQLAlchemy models
├── schemas/         Pydantic request/response models
├── services/        Business logic (shipment, state machine, artifact, ai)
└── repositories/    Data access

apps/api/alembic/    Migrations
apps/worker/worker_app/
├── tasks/           Celery tasks (pipeline)
├── services/        Pipeline stages + orchestration
└── observability.py Metrics server, queue gauge, Celery signals

infrastructure/      docker/, kubernetes/, helm/, observability/
scripts/             cluster-*.sh, health-check.sh, smoke_*.py
tests/               apps/api/tests/ (single suite, both packages share a venv)
```

## Testing

```bash
make test
```

- Unit tests: state machine (full allowed/forbidden matrix), validation,
  artifact rules, retry/idempotency, AI parsing, password/token handling
- API tests: every endpoint's success and failure paths, role matrix
- Integration: real MinIO (`requires_minio`), real PostgreSQL

Tests use a **dedicated `shipment_test` database** (created automatically) and
an in-memory artifact store — they never touch the dev stack or MinIO, so you
can run the suite while `make dev` is up.

Skipped tests report a clear reason when a dependency (postgres, minio) is not
reachable.

## Code quality

```bash
make lint && make typecheck && make test
```

Run all three before committing. Conventions (also in `AGENTS.md`):

- Type hints everywhere; Pydantic for all schemas/config
- Structured JSON logging — never log secrets
- Safe HTTP errors (no internals leaked)
- Every shipment status change goes through the state machine service
- Idempotent operations: retries/duplicates must not double-publish

## Database migrations

```bash
make migration m="add shipment index"   # autogenerate
make migrate                            # apply
```

Alembic lives in `apps/api`. The initial migration creates the core tables;
the second adds `users` with seeded development accounts (idempotent).

## Debugging

- API logs: `docker compose logs -f api` (JSON lines)
- Worker logs: `docker compose logs -f worker`
- Metrics: `curl localhost:8000/metrics` and `curl localhost:9100/metrics`
- Prometheus: `localhost:9090`, Grafana: `localhost:3000` (admin/shipforge)
- DB: `docker compose exec postgres psql -U shipment -d shipment`
- Event trail: `GET /api/v1/shipments/{id}/events`

## Failure simulation

Deterministic failure products (product name triggers the failure):

| Product | Fails in | Error code |
|---|---|---|
| `failure-validation` | Validate | `VALIDATION_ERROR` |
| `failure-build` | Build | `BUILD_FAILED` |
| `failure-scan` | Scan | `SCAN_FAILED` |
| `failure-timeout` | Validate | `TIMEOUT` |

Use them to exercise `FAILED` → `retry` → success without random failures.
