# ShipForge — Agent Team Conventions

This repository is a local, production-oriented software shipment platform.
The main agent acts as **TeamLead** and dispatches the specialist subagents in
`.opencode/agent/`. All agents follow the conventions below.

## Project map

| Path | Owner | Purpose |
|---|---|---|
| `apps/api/` | backend | FastAPI app: `api/`, `core/`, `models/`, `schemas/`, `services/`, `repositories/` |
| `apps/worker/` | backend | Celery worker: `tasks/`, `services/` |
| `infrastructure/docker/` | devops | Dockerfiles (api, worker) |
| `infrastructure/kubernetes/` | devops | Raw k8s manifests |
| `infrastructure/helm/` | devops | Helm chart + values files |
| `scripts/` | devops | dev.sh, test.sh, cluster-*.sh, health-check.sh |
| `.github/workflows/` | devops | test.yml, build.yml, security.yml |
| `apps/*/tests/`, `tests/` | qa | pytest suites |
| `docs/` | docs / sre | architecture, api, development, deployment, troubleshooting, security |
| `README.md` | docs | Project entry point |

## Shipment state machine (source of truth)

```text
CREATED    -> VALIDATING
VALIDATING -> BUILDING | FAILED
BUILDING   -> SCANNING | FAILED
SCANNING   -> READY    | FAILED
READY      -> PUBLISHED | FAILED
FAILED     -> VALIDATING
```

- Any other transition is invalid and must raise a controlled application error.
- Every transition MUST write a `shipment_events` row.
- Pipeline stages run in the worker, never synchronously in the API.

## Error codes (extend as needed, keep SCREAMING_SNAKE)

`VALIDATION_ERROR`, `ARTIFACT_MISSING`, `ARTIFACT_TOO_LARGE`,
`ARTIFACT_INVALID_TYPE`, `BUILD_FAILED`, `SCAN_FAILED`, `TIMEOUT`,
`DEPENDENCY_ERROR`, `INVALID_TRANSITION`, `NOT_FOUND`, `UNAUTHORIZED`,
`FORBIDDEN`, `CONFLICT`, `INTERNAL_ERROR`

## Logging (structured JSON, all services)

Required fields: `timestamp`, `level`, `service`, `message`.
Contextual fields where applicable: `shipment_id`, `task_id`, `stage`,
`error_code`. Never log secrets, tokens, passwords, or raw connection strings.

## Hard rules

1. **No secrets in git.** Configuration comes from environment / ConfigMap /
   Secret. `.env` is gitignored; only `.env.example` is committed.
2. **Type hints everywhere** in Python; Pydantic for all request/response and
   config schemas.
3. **Never leak internals** in HTTP errors — safe messages externally, full
   detail in structured logs.
4. **Idempotency**: retries and duplicate requests must not publish twice or
   create duplicate artifacts/transitions.
5. **Tests before Kubernetes milestones** — unit + integration + API tests must
   be green before infra phases proceed.
6. **Scope rule** (from PLAN.md §37): every component must solve a real problem;
   do not add technology for its own sake.
7. Run `make lint`, `make typecheck`, and `make test` before declaring work
   done. Never commit secrets or broken builds.

## Definition of done (per PLAN.md §34)

Clean structure, type hints, validated inputs, exception handling, structured
logging, config management, migrations, async processing with retries and
idempotency, non-root containers, probes/limits, CI, metrics, docs, JWT auth,
advisory-only AI. Check items against `PLAN.md` when completing milestones.

## Milestone checkpoints

Work proceeds milestone by milestone (M0 scaffolding → M7 docs). The TeamLead
reports to the user at each checkpoint. Agents report back: what was built,
files touched, verification commands run and their results, and any blockers.
