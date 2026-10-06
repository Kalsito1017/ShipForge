# Local Production-Ready Software Shipment Platform

## 1. Project Overview

Build a production-oriented **Repository-Based Software Shipment Platform** inspired by the type of software distribution infrastructure used by large enterprise organizations such as SAP.

The platform manages the lifecycle of software releases:

```text
Release
   |
   v
Upload Artifact
   |
   v
Validate
   |
   v
Build
   |
   v
Scan
   |
   v
Ready
   |
   v
Publish
```

The entire project runs **locally**.

There will be no public production deployment.

However, the application must be designed and implemented using production-quality engineering practices.

The objective is to demonstrate competence in:

* Python
* REST APIs
* software architecture
* PostgreSQL
* asynchronous processing
* Linux
* Bash
* Docker
* Kubernetes
* Helm
* CI/CD
* testing
* observability
* infrastructure concepts
* AI/LLM integration
* troubleshooting
* secure application development

---

# 2. Project Philosophy

## Local deployment does not mean toy architecture.

The system should run entirely on a developer workstation, but should be designed so that moving it to a real Kubernetes environment would require configuration changes rather than a complete architectural rewrite.

The project should therefore follow production-oriented principles:

* configuration outside source code
* secrets outside source code
* stateless API services
* asynchronous background processing
* database migrations
* structured logging
* health checks
* readiness checks
* graceful shutdown
* retries
* timeouts
* idempotency
* authentication
* authorization
* automated testing
* containerization
* Kubernetes deployment
* resource management
* observability
* security scanning
* reproducible builds

---

# 3. Deployment Targets

There are two local environments.

## Development Environment

Docker Compose:

```text
Docker Compose
│
├── API
├── Worker
├── PostgreSQL
├── Redis
└── MinIO
```

Start with:

```bash
make dev
```

This environment is optimized for development speed.

---

## Production-Like Environment

Local Kubernetes cluster using either:

* kind
* k3d

Recommended:

```text
kind
```

Architecture:

```text
Local Kubernetes Cluster
│
├── API
├── Worker
├── PostgreSQL
├── Redis
├── MinIO
├── Prometheus
└── Grafana
```

Deployment:

```bash
make cluster
make deploy
```

The application is still running only on the local machine.

---

# 4. Main Use Case

A developer wants to release:

```text
payment-service
version: 2.4.1
```

The developer uploads:

```text
payment-service-2.4.1.tar.gz
```

The platform creates a shipment.

The shipment moves through:

```text
CREATED
   |
   v
VALIDATING
   |
   v
BUILDING
   |
   v
SCANNING
   |
   v
READY
   |
   v
PUBLISHED
```

If any stage fails:

```text
BUILDING
   |
   X
FAILED
```

The failure is recorded.

The user can inspect:

* current status
* previous states
* logs
* failure reason
* processing duration
* artifact information

---

# 5. Core Architecture

```text
                         Local Machine
                              |
                       Kubernetes / Docker
                              |
                       +--------------+
                       |   FastAPI    |
                       |     API      |
                       +------+-------+
                              |
               +--------------+--------------+
               |              |              |
               v              v              v
         PostgreSQL        Redis           MinIO
               |              |              |
               |              v              |
               |         Celery Worker       |
               |              |              |
               |       +------+------+        |
               |       |      |      |        |
               |       v      v      v        |
               |    Validate Build  Scan      |
               |                             |
               +-------------+---------------+
                             |
                             v
                         Published
                          Artifact

                +----------------------+
                |    Observability     |
                | Prometheus + Grafana |
                +----------------------+

                +----------------------+
                |   AI Incident Tool   |
                |       LLM API        |
                +----------------------+
```

---

# 6. Technology Stack

## Application

```text
Python 3.12+
FastAPI
Pydantic
SQLAlchemy
Alembic
```

## Database

```text
PostgreSQL
```

## Background Processing

```text
Celery
Redis
```

## Artifact Storage

```text
MinIO
```

## Testing

```text
pytest
pytest-asyncio
httpx
```

## Code Quality

```text
Ruff
mypy
pre-commit
```

## Containers

```text
Docker
Docker Compose
```

## Kubernetes

```text
kind
Kubernetes
Helm
```

## Observability

```text
Prometheus
Grafana
structured JSON logging
```

## CI

```text
GitHub Actions
```

## Infrastructure

```text
Terraform
```

Terraform is optional for the final local Kubernetes environment. It should be included only after the application and Kubernetes deployment are working.

## AI

```text
LLM API
Pydantic structured output
```

---

# 7. Repository Structure

```text
shipment-platform/
│
├── apps/
│   │
│   ├── api/
│   │   ├── app/
│   │   │   ├── api/
│   │   │   │   └── v1/
│   │   │   │
│   │   │   ├── core/
│   │   │   ├── models/
│   │   │   ├── schemas/
│   │   │   ├── services/
│   │   │   ├── repositories/
│   │   │   ├── workers/
│   │   │   └── main.py
│   │   │
│   │   ├── tests/
│   │   ├── pyproject.toml
│   │   └── Dockerfile
│   │
│   └── worker/
│       ├── app/
│       │   ├── tasks/
│       │   ├── services/
│       │   └── main.py
│       │
│       ├── tests/
│       ├── pyproject.toml
│       └── Dockerfile
│
├── infrastructure/
│   │
│   ├── docker/
│   │
│   ├── kubernetes/
│   │
│   ├── helm/
│   │   └── shipment-platform/
│   │
│   └── terraform/
│
├── scripts/
│   ├── dev.sh
│   ├── test.sh
│   ├── cluster-create.sh
│   ├── cluster-delete.sh
│   └── health-check.sh
│
├── docs/
│   ├── architecture.md
│   ├── api.md
│   ├── development.md
│   ├── deployment.md
│   ├── troubleshooting.md
│   └── security.md
│
├── .github/
│   └── workflows/
│       ├── test.yml
│       ├── build.yml
│       └── security.yml
│
├── docker-compose.yml
├── Makefile
├── README.md
└── PLAN.md
```

---

# 8. Phase 0 — Local Development Environment

## Goal

Make development reproducible.

Install/check:

```text
Python
Docker
Docker Compose
Git
kubectl
kind
Helm
```

Create:

```text
Makefile
docker-compose.yml
.env.example
```

The repository must never contain real secrets.

Example:

```text
.env.example
```

contains:

```text
DATABASE_URL=
REDIS_URL=
MINIO_ENDPOINT=
MINIO_ACCESS_KEY=
MINIO_SECRET_KEY=
LLM_API_KEY=
```

Real `.env` files must be ignored by Git.

---

# 9. Phase 1 — Python Application Foundation

## Goal

Create a clean, maintainable Python service.

Implement:

* FastAPI application
* configuration management
* dependency injection
* structured logging
* exception handling
* health endpoint
* readiness endpoint

Endpoints:

```http
GET /health
GET /ready
```

Expected:

```json
{
  "status": "ok"
}
```

---

# 10. Phase 2 — PostgreSQL

## Goal

Persist application state.

Use:

```text
SQLAlchemy
Alembic
PostgreSQL
```

Create the initial database schema.

## shipments

```text
id
product
version
artifact_name
artifact_path
status
error_code
error_message
created_at
updated_at
published_at
```

## shipment_events

```text
id
shipment_id
event_type
message
metadata
created_at
```

Use database migrations.

Never modify production-like schema manually.

Migration example:

```bash
alembic upgrade head
```

---

# 11. Phase 3 — Shipment API

Implement:

```http
POST   /api/v1/shipments
GET    /api/v1/shipments
GET    /api/v1/shipments/{id}
GET    /api/v1/shipments/{id}/events
POST   /api/v1/shipments/{id}/retry
```

The API must:

* validate input
* return correct HTTP status codes
* use Pydantic schemas
* handle database errors
* produce structured logs
* avoid leaking internal exceptions

---

# 12. Phase 4 — Shipment State Machine

Implement the lifecycle:

```text
CREATED
VALIDATING
BUILDING
SCANNING
READY
PUBLISHED
FAILED
```

Allowed transitions:

```text
CREATED -> VALIDATING

VALIDATING -> BUILDING
VALIDATING -> FAILED

BUILDING -> SCANNING
BUILDING -> FAILED

SCANNING -> READY
SCANNING -> FAILED

READY -> PUBLISHED
READY -> FAILED

FAILED -> VALIDATING
```

Invalid transitions must raise a controlled application error.

Every state transition must create a `shipment_event`.

Example:

```text
10:20 CREATED
10:20 VALIDATING
10:21 BUILDING
10:23 FAILED
```

---

# 13. Phase 5 — Artifact Management

Add MinIO.

Implement:

```http
POST /api/v1/shipments/{id}/artifact
GET  /api/v1/shipments/{id}/artifact
```

Requirements:

* maximum artifact size
* filename validation
* content type validation
* unique storage path
* metadata stored in PostgreSQL
* artifact stored in MinIO
* artifact existence validation

Storage layout:

```text
artifacts/
└── payment-service/
    └── 2.4.1/
        └── payment-service-2.4.1.tar.gz
```

---

# 14. Phase 6 — Asynchronous Processing

Add:

```text
Redis
Celery
```

The API should never perform long-running shipment operations synchronously.

Flow:

```text
POST /shipments
       |
       v
Create shipment
       |
       v
Queue task
       |
       v
Return 202
       |
       v
Celery Worker
```

Worker stages:

```text
Validate
   |
Build
   |
Scan
   |
Publish
```

Each stage:

* updates shipment status
* records an event
* logs structured information
* handles exceptions
* uses appropriate retry behavior

---

# 15. Phase 7 — Retry and Idempotency

This is an important production-readiness requirement.

The system must handle:

* duplicate requests
* worker retries
* repeated processing
* task failures

A shipment should not accidentally be published twice.

Implement idempotent operations.

For example:

```text
POST /shipments/{id}/publish
```

should safely handle the case where the shipment is already published.

Celery retries must not create duplicate artifacts or duplicate state transitions.

---

# 16. Phase 8 — Failure Simulation

Create deterministic failure scenarios.

Examples:

```text
failure-validation
failure-build
failure-scan
failure-timeout
```

Example:

```text
product = failure-build
```

causes the build stage to fail.

This allows the platform to demonstrate real troubleshooting without depending on random failures.

Expected behavior:

```text
BUILDING
   |
   X
FAILED
   |
   +--> error_code
   +--> error_message
   +--> event
   +--> logs
```

---

# 17. Phase 9 — Testing

Testing must be implemented before Kubernetes.

## Unit Tests

Test:

* state machine
* validation
* business logic
* artifact validation
* retry logic
* idempotency
* AI response parsing

## Integration Tests

Test:

```text
API + PostgreSQL
API + Redis
Worker + PostgreSQL
Worker + MinIO
```

## API Tests

Test:

```text
POST /shipments
GET /shipments
GET /shipments/{id}
POST /shipments/{id}/retry
```

Test both success and failure paths.

---

# 18. Phase 10 — Docker

Create production-oriented Docker images.

Requirements:

* minimal base image
* non-root user
* pinned dependencies
* health check
* environment-based configuration
* no secrets inside images

Services:

```text
api
worker
```

Docker Compose:

```text
api
worker
postgres
redis
minio
```

Start:

```bash
docker compose up -d
```

Stop:

```bash
docker compose down
```

---

# 19. Phase 11 — Docker Security

Add:

* dependency scanning
* image scanning
* non-root execution
* read-only filesystem where practical
* minimal Linux packages
* no unnecessary capabilities
* `.dockerignore`

The goal is not perfect security.

The goal is demonstrating that security was considered during application/container design.

---

# 20. Phase 12 — CI

Create GitHub Actions.

Pull request pipeline:

```text
Checkout
   |
Install
   |
Lint
   |
Type Check
   |
Unit Tests
   |
Integration Tests
```

Main branch:

```text
Tests
   |
Docker Build
   |
Image Scan
```

No cloud deployment is required.

The CI pipeline validates the project; deployment remains local.

---

# 21. Phase 13 — Local Kubernetes

Create a local kind cluster.

Example:

```bash
kind create cluster --name shipment-platform
```

Build Docker images locally.

Load them into kind.

Deploy the application to Kubernetes.

Required resources:

```text
Namespace
Deployment
Service
ConfigMap
Secret
Ingress
```

Application components:

```text
API
Worker
PostgreSQL
Redis
MinIO
```

---

# 22. Phase 14 — Kubernetes Production Practices

The Kubernetes deployment must include:

## Readiness probe

Determines whether the pod can receive traffic.

## Liveness probe

Determines whether the application needs restarting.

## Resource requests

Example:

```text
CPU
Memory
```

## Resource limits

Prevent one container from consuming unlimited resources.

## Graceful shutdown

The API must properly handle termination signals.

## Configuration

Configuration must come from:

```text
ConfigMap
Secret
Environment variables
```

not hardcoded values.

---

# 23. Phase 15 — Helm

Create:

```text
infrastructure/helm/shipment-platform
```

Helm should manage:

```text
API
Worker
PostgreSQL
Redis
MinIO
Ingress
Config
Secrets
```

Use:

```text
values.yaml
```

for environment-specific configuration.

Example:

```text
values.yaml
values-dev.yaml
values-local.yaml
```

Deployment:

```bash
helm upgrade --install shipment-platform ./infrastructure/helm/shipment-platform
```

---

# 24. Phase 16 — Observability

Add:

```text
Prometheus
Grafana
```

Expose application metrics.

Important metrics:

```text
shipments_created_total
shipments_failed_total
shipments_published_total
shipment_processing_duration_seconds
shipment_queue_size
api_requests_total
api_request_duration_seconds
worker_tasks_total
worker_task_failures_total
```

---

# 25. Phase 17 — Structured Logging

All services must produce structured logs.

Example:

```json
{
  "timestamp": "2026-10-06T13:20:10Z",
  "level": "ERROR",
  "service": "shipment-worker",
  "shipment_id": "123",
  "stage": "BUILDING",
  "error_code": "DEPENDENCY_ERROR",
  "message": "Dependency installation failed"
}
```

Logs must allow troubleshooting without attaching a debugger.

Include:

* shipment ID
* task ID where applicable
* service name
* stage
* error code
* timestamp

---

# 26. Phase 18 — AI Incident Assistant

Build an AI-powered troubleshooting feature.

Endpoint:

```http
POST /api/v1/shipments/{id}/analyze
```

The service collects:

```text
Shipment information
Shipment events
Application logs
Worker logs
Failure reason
Environment information
```

The LLM receives structured context.

Expected output:

```json
{
  "category": "DEPENDENCY",
  "root_cause": "Required package version is unavailable.",
  "confidence": 0.94,
  "severity": "MEDIUM",
  "recommendations": [
    "Check package registry availability.",
    "Verify dependency version.",
    "Rebuild the artifact."
  ]
}
```

The response must be validated using Pydantic.

The AI must be **advisory only**.

It must not automatically:

* execute shell commands
* modify infrastructure
* delete artifacts
* deploy code
* restart production services

---

# 27. Phase 19 — Authentication

Implement JWT authentication.

Users:

```text
developer
release_manager
admin
```

Permissions:

## Developer

```text
Create shipment
View shipments
View events
View logs
```

## Release Manager

```text
All developer permissions
Retry shipment
Publish shipment
```

## Admin

```text
All permissions
```

Passwords must be securely hashed.

No plaintext passwords.

---

# 28. Phase 20 — Security

Implement basic application security.

Requirements:

* input validation
* authentication
* authorization
* password hashing
* secret management
* artifact size limits
* filename validation
* dependency scanning
* Docker image scanning
* non-root containers
* no secrets in Git
* safe error responses
* request timeouts
* database query parameterization
* controlled file access

---

# 29. Phase 21 — Terraform

Terraform is an optional final layer.

It should be used for **local infrastructure concepts**, not cloud deployment.

The purpose is to demonstrate familiarity with Infrastructure as Code.

Do not force Terraform into every component.

If Terraform makes the local environment unnecessarily complicated, keep it minimal.

The application itself remains managed by Helm.

Architecture:

```text
Terraform
   |
   v
Infrastructure

Helm
   |
   v
Application
```

---

# 30. Phase 22 — Troubleshooting Documentation

Create real incident scenarios.

## Scenario 1 — API CrashLoopBackOff

Investigate:

```bash
kubectl get pods
kubectl describe pod
kubectl logs
kubectl get events
```

## Scenario 2 — Database unavailable

Investigate:

```text
Pod
Service
DNS
Credentials
Connection string
```

## Scenario 3 — Shipment stuck

Investigate:

```text
Redis
Celery
Worker
Database
```

## Scenario 4 — Artifact upload fails

Investigate:

```text
API
MinIO
credentials
bucket
network
```

## Scenario 5 — Ingress unavailable

Investigate:

```text
Pod
Service
Ingress
Port
```

Document the investigation process in:

```text
docs/troubleshooting.md
```

---

# 31. Phase 23 — Developer Experience

Create a useful Makefile.

Example commands:

```text
make install
make test
make lint
make format
make typecheck

make dev
make dev-down

make cluster
make cluster-delete

make build
make deploy
make undeploy

make logs
make status

make migrate
make migration

make clean
```

A new developer should be able to clone the repository and understand how to run it from the README.

---

# 32. Phase 24 — Documentation

README must contain:

## Project Overview

What problem does the platform solve?

## Architecture

Include architecture diagram.

## Local Requirements

List required tools.

## Development

Explain Docker Compose.

## Kubernetes

Explain kind.

## Deployment

Explain Helm.

## Testing

Explain test strategy.

## Observability

Explain Prometheus/Grafana.

## AI

Explain the incident assistant.

## Troubleshooting

Provide common commands.

---

# 33. Development Workflow

Normal development should look like:

```text
1. Create feature branch
        |
        v
2. Implement change
        |
        v
3. Run unit tests
        |
        v
4. Run lint/type checking
        |
        v
5. Run integration tests
        |
        v
6. Build Docker image
        |
        v
7. Test with Docker Compose
        |
        v
8. Deploy to local Kubernetes
        |
        v
9. Verify health/metrics/logs
```

---

# 34. Definition of Done

The project is complete when the following are true.

## Python

* [ ] Clean application structure
* [ ] Type hints
* [ ] Pydantic validation
* [ ] Exception handling
* [ ] Logging
* [ ] Configuration management

## API

* [ ] Shipment creation
* [ ] Shipment retrieval
* [ ] Shipment listing
* [ ] Artifact upload
* [ ] Artifact download
* [ ] Retry
* [ ] Publish
* [ ] Health endpoint
* [ ] Readiness endpoint

## Database

* [ ] PostgreSQL
* [ ] SQLAlchemy
* [ ] Alembic
* [ ] Migrations
* [ ] Shipment events

## Async

* [ ] Redis
* [ ] Celery
* [ ] Background processing
* [ ] Retry handling
* [ ] Idempotency

## Docker

* [ ] API image
* [ ] Worker image
* [ ] Non-root containers
* [ ] Docker Compose
* [ ] Health checks
* [ ] Security scanning

## Kubernetes

* [ ] kind cluster
* [ ] API Deployment
* [ ] Worker Deployment
* [ ] Services
* [ ] ConfigMaps
* [ ] Secrets
* [ ] Ingress
* [ ] Readiness probes
* [ ] Liveness probes
* [ ] Resource limits

## Helm

* [ ] Helm chart
* [ ] Configurable values
* [ ] Install
* [ ] Upgrade
* [ ] Rollback

## CI/CD

* [ ] Automated tests
* [ ] Linting
* [ ] Type checking
* [ ] Docker build
* [ ] Security scan

## Observability

* [ ] Prometheus
* [ ] Grafana
* [ ] Application metrics
* [ ] Structured logs
* [ ] Troubleshooting documentation

## AI

* [ ] LLM integration
* [ ] Structured output
* [ ] Pydantic validation
* [ ] Failure analysis
* [ ] Remediation suggestions
* [ ] Advisory-only behavior

## Security

* [ ] JWT authentication
* [ ] Authorization
* [ ] Password hashing
* [ ] Secret management
* [ ] Input validation
* [ ] Dependency scanning

## Documentation

* [ ] README
* [ ] Architecture documentation
* [ ] API documentation
* [ ] Deployment documentation
* [ ] Troubleshooting documentation
* [ ] Security documentation

---

# 35. Final Local Architecture

```text
                         LOCAL MACHINE
                              |
              +---------------+---------------+
              |                               |
              v                               v
        Docker Compose                   kind Cluster
        Development                     Production-like
              |                               |
              |                         +-----+-----+
              |                         |           |
              |                         v           v
              |                       API        Worker
              |                         |           |
              |                         +-----+-----+
              |                               |
              |                  +------------+------------+
              |                  |            |            |
              |                  v            v            v
              |             PostgreSQL     Redis         MinIO
              |                               |
              |                               v
              |                             Celery
              |
              +-------------------------------+

                     Observability
                           |
                +----------+----------+
                |                     |
                v                     v
            Prometheus             Grafana

                     AI Assistant
                           |
                           v
                       LLM API
```

---

# 36. Final Goal

The finished project should demonstrate the following engineering progression:

```text
Python
  |
  v
FastAPI
  |
  v
PostgreSQL
  |
  v
Async Processing
  |
  v
Docker
  |
  v
CI
  |
  v
Kubernetes
  |
  v
Helm
  |
  v
Observability
  |
  v
Security
  |
  v
AI-assisted Operations
```

Everything runs locally.

There is no requirement to deploy anything publicly.

The project should nevertheless be designed as if it were going to be deployed to a real enterprise Kubernetes environment.

---

# 37. Scope Rule

Do not add technologies just to make the technology list larger.

Every component must solve a real problem.

For example:

```text
PostgreSQL
    -> persistent shipment state

Redis
    -> task broker

Celery
    -> asynchronous processing

MinIO
    -> artifact storage

Docker
    -> reproducible environments

Kubernetes
    -> container orchestration

Helm
    -> Kubernetes application packaging

Prometheus
    -> metrics

Grafana
    -> visualization

LLM
    -> incident analysis

Terraform
    -> infrastructure-as-code practice
```

If a technology does not have a clear architectural purpose, do not add it.

---

# 38. Success Criteria

The project succeeds when you can demonstrate this entire scenario locally:

```text
1. Developer creates a release
        |
        v
2. Artifact is uploaded
        |
        v
3. API creates shipment
        |
        v
4. Celery processes shipment
        |
        v
5. Validation runs
        |
        v
6. Build runs
        |
        v
7. Scan runs
        |
        v
8. Artifact is published
        |
        v
9. Metrics are recorded
        |
        v
10. Logs are available
        |
        v
11. Grafana displays the system
        |
        v
12. Introduce a controlled failure
        |
        v
13. System records the failure
        |
        v
14. AI analyzes the failure
        |
        v
15. AI provides a probable root cause
        |
        v
16. Developer fixes the problem
        |
        v
17. Shipment is retried
        |
        v
18. Shipment succeeds
```

This is the primary demonstration scenario for the project.
