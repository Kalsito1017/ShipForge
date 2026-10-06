---
name: shipforge-conventions
description: Use when implementing or reviewing any ShipForge code - covers repo layout, the shipment state machine, error codes, structured logging fields, and hard rules (secrets, type hints, idempotency). Front-load when working in apps/, infrastructure/, or tests/.
---

# ShipForge Conventions

Binding conventions for all ShipForge work. `AGENTS.md` is the durable copy —
keep them in sync.

## Repository layout

- `apps/api/` — FastAPI app (`api/v1/` routers, `core/` config, `models/` ORM,
  `schemas/` Pydantic, `services/` logic, `repositories/` data access)
- `apps/worker/` — Celery worker (`tasks/`, `services/` pipeline stages)
- `infrastructure/` — docker/, kubernetes/, helm/
- `scripts/`, `docs/`, `tests/`

## State machine (source of truth)

```text
CREATED    -> VALIDATING
VALIDATING -> BUILDING | FAILED
BUILDING   -> SCANNING | FAILED
SCANNING   -> READY    | FAILED
READY      -> PUBLISHED | FAILED
FAILED     -> VALIDATING
```

Any other transition raises a controlled `INVALID_TRANSITION` application
error. Every transition writes a `shipment_events` row.

## Error codes

`VALIDATION_ERROR`, `ARTIFACT_MISSING`, `ARTIFACT_TOO_LARGE`,
`ARTIFACT_INVALID_TYPE`, `BUILD_FAILED`, `SCAN_FAILED`, `TIMEOUT`,
`DEPENDENCY_ERROR`, `INVALID_TRANSITION`, `NOT_FOUND`, `UNAUTHORIZED`,
`FORBIDDEN`, `CONFLICT`, `INTERNAL_ERROR` — SCREAMING_SNAKE, extend as needed.

## Structured logging (JSON, all services)

Required: `timestamp`, `level`, `service`, `message`. Contextual:
`shipment_id`, `task_id`, `stage`, `error_code`. Never log secrets or raw
connection strings.

## Hard rules

1. No secrets in git (`.env` ignored; `.env.example` committed).
2. Type hints everywhere; Pydantic for all request/response/config schemas.
3. Never leak internals in HTTP errors (safe message out, detail in logs).
4. Idempotency: retries/duplicates never publish twice or duplicate state.
5. Tests green before Kubernetes milestones.
6. Scope rule (PLAN.md §37): every component solves a real problem.
7. `make lint`, `make typecheck`, `make test` before declaring done.
