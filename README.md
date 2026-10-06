# ShipForge — Local Software Shipment Platform

A production-oriented, repository-based software shipment platform inspired by
enterprise software distribution infrastructure (e.g. SAP-style release
management). It manages the lifecycle of software releases:

```text
Release -> Upload Artifact -> Validate -> Build -> Scan -> Ready -> Publish
```

Everything runs **locally** (Docker Compose for development, kind + Helm for a
production-like Kubernetes environment). There is no public deployment, but the
system is engineered as if it were going to a real enterprise cluster.

## Features

- **Shipment lifecycle** — explicit state machine (`CREATED -> VALIDATING ->
  BUILDING -> SCANNING -> READY -> PUBLISHED`, or `FAILED`) with a full event
  trail per shipment
- **Artifact management** — uploads to MinIO with size/filename/content-type
  validation, checksums, and unique storage paths
- **Asynchronous processing** — Celery + Redis workers run the pipeline stages;
  the API never blocks on long-running work
- **Idempotency & retries** — duplicate requests and worker retries cannot
  publish twice or corrupt state
- **Failure simulation** — deterministic `failure-*` products for realistic
  troubleshooting demos
- **AI incident assistant** — advisory-only LLM analysis of failures with
  Pydantic-validated structured output (offline mock mode when no API key)
- **AuthN/AuthZ** — JWT with `developer`, `release_manager`, `admin` roles
- **JWT auth** — `developer` / `release_manager` / `admin` roles with an
  explicit permission matrix; bcrypt password hashing
- **Observability** — Prometheus metrics, Grafana dashboards, structured JSON
  logs
- **Production practices** — migrations, health/readiness probes, graceful
  shutdown, non-root containers, resource limits, CI with lint/type/security
  scans

## Architecture

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
                                       |
                                Validate/Build/Scan

           Observability: Prometheus + Grafana
           AI Assistant:  OpenAI-compatible LLM API (optional)
```

## Requirements

| Tool | Purpose |
|---|---|
| Python 3.12+ | Application runtime |
| Docker + Docker Compose | Development environment |
| git | Version control |
| make | Developer workflow commands |
| kubectl, kind, Helm | Local Kubernetes environment |

## Quickstart

```bash
git clone <this-repo> shipforge
cd shipforge

cp .env.example .env    # JWT_SECRET=openssl rand -hex 32 (LLM_API_KEY optional)

make install            # install Python dependencies
make dev                # start API, Worker, PostgreSQL, Redis, MinIO, monitoring
make migrate            # apply migrations (seeds development users)

# end-to-end verification: login -> upload -> publish -> failure -> retry -> AI
python3 scripts/smoke_compose.py
```

API: `http://localhost:8000` — interactive docs at `/docs`,
health at `/health`, readiness at `/ready`, metrics at `/metrics`.

Get a token (seeded dev users: `developer/developer`,
`release_manager/release_manager`, `admin/admin`):

```bash
curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"username":"admin","password":"admin"}'
```

## Configuration

All configuration comes from environment variables (see `.env.example`).
Secrets never live in source control:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Celery broker/backend |
| `MINIO_*` | Artifact storage endpoint and credentials |
| `JWT_SECRET` | Token signing secret |
| `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | AI assistant (optional) |

## Project Layout

```text
apps/
├── api/         FastAPI application (REST API, services, repositories)
└── worker/      Celery worker (pipeline stages: validate, build, scan, publish)
infrastructure/
├── docker/      Dockerfiles and container config
├── kubernetes/  Raw manifests
└── helm/        Helm chart (API, Worker, PostgreSQL, Redis, MinIO, Ingress)
scripts/         Dev/test/cluster helper scripts
docs/            Architecture, API, deployment, troubleshooting, security
```

## Make Targets

```text
make install        Install dependencies
make test           Run the test suite
make lint           Lint (ruff)
make format         Format code
make typecheck      Type check (mypy)

make dev            Start development environment (Docker Compose)
make dev-down       Stop development environment

make cluster        Create local kind cluster
make cluster-delete Delete the kind cluster

make build          Build Docker images
make deploy         Deploy to local Kubernetes (Helm)
make undeploy       Remove the deployment

make logs           Tail service logs
make status         Show service/cluster status

make migrate        Apply database migrations
make migration      Create a new migration
make clean          Remove build/test artifacts
```

## Monitoring

| Tool | URL | Credentials |
|---|---|---|
| Prometheus | http://localhost:9090 | — |
| Grafana | http://localhost:3000 | admin / shipforge |

The "ShipForge Overview" dashboard is provisioned automatically (shipment
lifecycle, processing durations, API latency, worker tasks, queue depth).

## Testing

- **Unit tests** — state machine, validation, business logic, idempotency
- **Integration tests** — API + PostgreSQL, worker + MinIO, Celery + Redis
- **API tests** — endpoint success and failure paths

Run everything with `make test`.

## Observability

Prometheus scrapes application metrics (shipment counts, processing durations,
API latency, worker task stats). Grafana ships with pre-built dashboards in the
kind environment. All services emit structured JSON logs with shipment IDs,
stages, and error codes for debugging without a debugger.

## AI Incident Assistant

`POST /api/v1/shipments/{id}/analyze` collects shipment context (status,
events, logs, failure reason) and asks an OpenAI-compatible LLM for a structured
diagnosis: category, root cause, confidence, severity, and recommendations —
validated with Pydantic. The assistant is **advisory only**: it never executes
commands, modifies infrastructure, or deploys anything. Without `LLM_API_KEY` a
deterministic offline mock is used.

## Documentation

| Document | Contents |
|---|---|
| [`docs/run-guide.md`](docs/run-guide.md) | **Step-by-step: run the platform and the full demo** |
| [`docs/architecture.md`](docs/architecture.md) | Components, data model, request flow |
| [`docs/api.md`](docs/api.md) | Endpoint reference, permissions, error codes |
| [`docs/development.md`](docs/development.md) | Dev workflow, testing, migrations |
| [`docs/deployment.md`](docs/deployment.md) | Compose and kind/Helm deployment |
| [`docs/security.md`](docs/security.md) | Security controls and limitations |
| [`docs/troubleshooting.md`](docs/troubleshooting.md) | Incident runbooks |

## Troubleshooting

See [`docs/troubleshooting.md`](docs/troubleshooting.md) for real incident
scenarios (CrashLoopBackOff, database unavailable, stuck shipments, upload
failures, ingress issues) with investigation commands.

## Security

- JWT authentication with role-based authorization
- Passwords hashed (bcrypt), never stored in plaintext
- Input validation, artifact size limits, filename/content-type checks
- No secrets in git; configuration via environment/ConfigMap/Secret
- Non-root containers, minimal images, dependency/image scanning in CI

Details in [`docs/security.md`](docs/security.md).
