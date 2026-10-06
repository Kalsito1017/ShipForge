---
name: shipforge-pipeline
description: Use when implementing or testing the shipment pipeline - Validate/Build/Scan/Publish stages, Celery task behavior, retry and idempotency rules, artifact validation, and deterministic failure-* products. Front-load for worker, state-machine, or retry work.
---

# ShipForge Pipeline Semantics

Behavioral contract for the asynchronous shipment pipeline.

## Flow

API `POST /api/v1/shipments` (and artifact upload) creates state and queues a
Celery task, then returns **202** — never process pipeline stages in the
request path. The worker runs: **Validate → Build → Scan → Publish**, each
stage updating status, writing events, and logging.

## Stage contract (per stage)

- Update shipment status (valid transitions only — see
  `shipforge-conventions`)
- Record a `shipment_events` row
- Emit a structured log with `shipment_id`, `stage`, `error_code` on failure
- Handle exceptions → controlled failure (`FAILED` + `error_code` +
  `error_message`), never an unhandled crash
- Retry behavior with backoff; retries must be idempotent

## Real checks vs simulation

- **Validate**: real checks — tar.gz integrity, size limit, filename rules,
  manifest/checksum verification
- **Build**: simulated deterministic build (extract + steps with logs/duration)
- **Scan**: real checks (checksum/manifest), optional Trivy when available;
  simulated scan otherwise

## Failure simulation products

Trigger deterministic failures by product name:

| Product | Fails in | Error code |
|---|---|---|
| `failure-validation` | Validate | `VALIDATION_ERROR` |
| `failure-build` | Build | `BUILD_FAILED` |
| `failure-scan` | Scan | `SCAN_FAILED` |
| `failure-timeout` | Any (hangs) | `TIMEOUT` |

Expected failure outcome: status `FAILED` + `error_code` + `error_message` +
event trail + logs.

## Idempotency requirements

- `POST /api/v1/shipments/{id}/publish` on an already-published shipment is
  safe (no second publish, no duplicate artifacts/events)
- `POST /api/v1/shipments/{id}/retry` transitions `FAILED → VALIDATING` and
  re-queues exactly once; duplicate retry calls do not double-queue
- Celery retries and redeliveries must not create duplicate artifacts,
  transitions, or publications (guard with state checks and unique keys)

## Artifact storage layout

```text
artifacts/{product}/{version}/{artifact_filename}
```

Metadata in PostgreSQL; binary in MinIO; existence validated on download.
