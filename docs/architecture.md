# ShipForge Architecture

## Overview

ShipForge is a repository-based software shipment platform: developers upload
release artifacts, the platform validates, builds, scans and publishes them
through an asynchronous pipeline, recording every step for auditability.

Everything runs locally (Docker Compose for development, kind + Helm for a
production-like Kubernetes environment), but the architecture is designed so
that moving to a real cluster is configuration-only.

## Component diagram

```text
                          LOCAL MACHINE
                               |
                +--------------+--------------+
                |                             |
         Docker Compose                 kind + Helm
          (development)              (production-like)
                |                             |
           +----+----+                   +----+----+
           |         |                   |         |
          API      Worker               API      Worker
           |         |                   |         |
           +----+----+-------------------+----+----+
                |         |                   |
           PostgreSQL   Redis  <--- Celery    MinIO
                |                               |
           shipment state                 artifact storage

           Observability: Prometheus + Grafana
           AI Assistant:  OpenAI-compatible LLM API (optional)
```

## Services

| Service | Role | Port |
|---|---|---|
| `api` | FastAPI REST API, request validation, task dispatch | 8000 |
| `worker` | Celery worker running the pipeline stages | 9100 (metrics) |
| `postgres` | System of record: shipments, events, logs, users | 5432 |
| `redis` | Celery broker (no persistence — broker role only) | 6379 |
| `minio` | S3-compatible artifact storage | 9000 (S3), 9001 (console) |
| `prometheus` | Metrics collection | 9090 |
| `grafana` | Dashboards | 3000 |

## Data model

- `shipments` — product, version, status, artifact metadata, error
  code/message, timestamps (`published_at` set on publication). Unique on
  `(product, version)`.
- `shipment_events` — one row per state transition or lifecycle event
  (`ARTIFACT_UPLOADED`, `PIPELINE_STARTED`, `STAGE_COMPLETED`, `PUBLISHED`,
  `PIPELINE_FAILED`, `RETRY`, …) with JSON metadata. The audit trail.
- `shipment_logs` — structured per-stage log lines (level, stage, message,
  context) for troubleshooting without a debugger.
- `users` — username, bcrypt password hash, role, active flag.

Migrations are managed with Alembic (`apps/api/alembic`). Never edit the
schema manually.

## Request flow

```text
1. Client            POST /api/v1/shipments  (JWT required)
2. API               validate -> insert shipment (CREATED) -> commit
3. API               dispatch Celery task -> 202 Accepted
4. Worker            Validate  (artifact exists, integrity, size, type)
5. Worker            Build     (deterministic simulated build)
6. Worker            Scan      (checksum, manifest scan)
7. Worker            Publish   (READY -> PUBLISHED, published_at)
```

Each stage updates status, writes a `shipment_events` row, emits structured
logs and metrics. Failures transition to `FAILED` with a stable `error_code`.

## State machine

The state machine (`apps/api/app/services/state_machine.py`) is the only
sanctioned path for status changes:

```text
CREATED    -> VALIDATING
VALIDATING -> BUILDING | FAILED
BUILDING   -> SCANNING  | FAILED
SCANNING   -> READY     | FAILED
READY      -> PUBLISHED | FAILED
FAILED     -> VALIDATING
PUBLISHED  -> (terminal)
```

Anything else raises `INVALID_TRANSITION`. Concurrency safety: the pipeline
and publish/retry paths take a `SELECT … FOR UPDATE` row lock, so concurrent
task deliveries (creation and artifact upload both dispatch) serialize instead
of double-publishing.

## Idempotency

- Task re-entry resumes from the current status; completed stages never
  re-run.
- A `PUBLISHED` shipment is a no-op on redelivery — never published twice.
- `POST /shipments/{id}/publish` is idempotent by design.
- Celery `acks_late` + bounded retries; duplicate deliveries are safe.

## Asynchronous processing

The API never performs long-running work inline. It commits state, then
dispatches `tasks.pipeline.process_shipment` to Celery (Redis broker). The
worker runs stages in forked child processes; Prometheus multiprocess mode
aggregates per-pid metric files so counters stay correct across the prefork
pool.

## Observability

- **Metrics** (PLAN §24): shipment counters, processing duration histogram,
  queue depth, API request rate/latency, worker task outcomes. Exposed on
  `/metrics` (API) and `:9100` (worker); scraped by Prometheus.
- **Structured logs**: JSON with `timestamp`, `level`, `service`, `message`
  plus contextual `shipment_id`, `stage`, `error_code`.
- **Dashboards**: Grafana "ShipForge Overview" (auto-provisioned).

## Security boundaries

- JWT bearer authentication with role-based authorization
  (developer / release_manager / admin).
- Passwords bcrypt-hashed; tokens signed with `JWT_SECRET` from the
  environment (never in git).
- Error responses never leak internals; detail goes to structured logs.
- Containers run as non-root with dropped capabilities and read-only rootfs.
- The AI assistant is advisory only — it cannot execute or mutate anything.

## Deployment targets

| Target | Command | Purpose |
|---|---|---|
| Docker Compose | `make dev` | Fast development loop |
| kind + Helm | `make cluster && make deploy` | Production-like local cluster |

The same images and the same Helm chart serve both; differences live in
values files (`values-local.yaml`, `values-dev.yaml`).
