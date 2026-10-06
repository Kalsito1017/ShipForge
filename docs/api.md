# ShipForge API Reference

All endpoints are served by the `api` service (default: `http://localhost:8000`).
Interactive OpenAPI docs are available at `/docs` while the service runs.

Version prefix: `/api/v1`

## Authentication

Obtain a JWT bearer token:

```http
POST /api/v1/auth/login
Content-Type: application/json

{"username": "admin", "password": "<password>"}
```

Response:

```json
{"access_token": "eyJhbGciOi...", "token_type": "bearer", "expires_in": 3600}
```

Send it on every protected request:

```http
Authorization: Bearer <access_token>
```

Seeded development users (change for real use): `developer/developer`,
`release_manager/release_manager`, `admin/admin`.

### Roles and permissions

| Permission | developer | release_manager | admin |
|---|---|---|---|
| `shipment:read` (list/get/events, download) | ✓ | ✓ | ✓ |
| `shipment:create` (create, upload artifact) | ✓ | ✓ | ✓ |
| `incident:analyze` | ✓ | ✓ | ✓ |
| `shipment:retry` | | ✓ | ✓ |
| `shipment:publish` | | ✓ | ✓ |
| `user:manage` | | | ✓ |

Failures return `401 UNAUTHORIZED` (missing/invalid/expired token) or
`403 FORBIDDEN` (valid token, insufficient role).

## Error envelope

All errors use a stable shape — internals are never leaked:

```json
{"error": {"code": "CONFLICT", "message": "Shipment for x 1.0.0 already exists"}}
```

Error codes: `VALIDATION_ERROR`, `ARTIFACT_MISSING`, `ARTIFACT_TOO_LARGE`,
`ARTIFACT_INVALID_TYPE`, `BUILD_FAILED`, `SCAN_FAILED`, `TIMEOUT`,
`DEPENDENCY_ERROR`, `INVALID_TRANSITION`, `NOT_FOUND`, `UNAUTHORIZED`,
`FORBIDDEN`, `CONFLICT`, `INTERNAL_ERROR`.

## Endpoints

### Health (public)

| Method | Path | Success | Notes |
|---|---|---|---|
| GET | `/health` | 200 `{"status":"ok"}` | Liveness |
| GET | `/ready` | 200 / 503 | Readiness (checks DB) |
| GET | `/metrics` | 200 | Prometheus exposition |

### Auth

| Method | Path | Auth | Success |
|---|---|---|---|
| POST | `/api/v1/auth/login` | public | 200 `TokenResponse` |
| GET | `/api/v1/auth/me` | any | 200 `UserResponse` |

### Shipments

| Method | Path | Permission | Success |
|---|---|---|---|
| POST | `/api/v1/shipments` | `shipment:create` | 202 `ShipmentRead` |
| GET | `/api/v1/shipments` | `shipment:read` | 200 `ShipmentList` |
| GET | `/api/v1/shipments/{id}` | `shipment:read` | 200 `ShipmentRead` |
| GET | `/api/v1/shipments/{id}/events` | `shipment:read` | 200 `[ShipmentEventRead]` |
| POST | `/api/v1/shipments/{id}/retry` | `shipment:retry` | 202 `ShipmentRead` |
| POST | `/api/v1/shipments/{id}/publish` | `shipment:publish` | 200 `ShipmentRead` |

**POST /api/v1/shipments** — body: `{"product": "payment-service", "version": "2.4.1"}`.
Creates the shipment (`CREATED`) and queues asynchronous processing (202).
Duplicate `(product, version)` → `409 CONFLICT`. Invalid input → `422`.

**GET /api/v1/shipments** — query params: `product`, `status`, `limit` (1–100,
default 20), `offset`. Returns `{"items": [...], "total": n, "limit": n, "offset": n}`.

**POST .../retry** — only `FAILED` shipments; transitions `FAILED -> VALIDATING`
and re-queues. Otherwise `409 CONFLICT`.

**POST .../publish** — only `READY` shipments; transitions `READY -> PUBLISHED`.
**Idempotent**: already-published shipments return 200 unchanged (never publish
twice).

### Artifacts

| Method | Path | Permission | Success |
|---|---|---|---|
| POST | `/api/v1/shipments/{id}/artifact` | `artifact:write` | 202 |
| GET | `/api/v1/shipments/{id}/artifact` | `shipment:read` | 200 (file download) |

Upload is `multipart/form-data` with a single `file` part. Validation:

- filename: safe charset, no path separators, `.tar.gz` / `.tgz` / `.zip`
- content type allowlist (`application/gzip`, `application/zip`,
  `application/octet-stream`, ...)
- size ≤ `ARTIFACT_MAX_SIZE_MB`
- archive integrity (corrupt/empty archives rejected)

Failures: `400` with `ARTIFACT_INVALID_TYPE` / `ARTIFACT_TOO_LARGE` /
`VALIDATION_ERROR`; `404` unknown shipment; `409` when the shipment is already
processing. Storage layout: `artifacts/{product}/{version}/{filename}`.

Download returns the bytes with `Content-Disposition` and `X-Artifact-SHA256`.
Missing artifact → `404 ARTIFACT_MISSING`.

### AI incident assistant

| Method | Path | Permission | Success |
|---|---|---|---|
| POST | `/api/v1/shipments/{id}/analyze` | `incident:analyze` | 200 `AnalyzeResponse` |

```json
{
  "shipment_id": "…",
  "analysis": {
    "category": "BUILD",
    "root_cause": "The build stage failed …",
    "confidence": 0.8,
    "severity": "MEDIUM",
    "recommendations": ["Review the build stage logs …"]
  },
  "source": "mock",
  "advisory": true
}
```

`category` ∈ `DEPENDENCY | ARTIFACT | VALIDATION | BUILD | SCAN | TIMEOUT |
INFRASTRUCTURE | CONFIGURATION | UNKNOWN`; `severity` ∈ `LOW | MEDIUM | HIGH |
CRITICAL`. `source` is `llm` when `LLM_API_KEY` is set (OpenAI-compatible
`/chat/completions`, output validated with Pydantic) or `mock` otherwise.

**Advisory only.** The assistant never executes commands, modifies
infrastructure, deletes artifacts, or deploys anything.

## Shipment lifecycle

```text
CREATED -> VALIDATING -> BUILDING -> SCANNING -> READY -> PUBLISHED
                |            |          |         |
                +------------+----------+---------+--> FAILED -> VALIDATING
```

Any other transition raises `INVALID_TRANSITION` (409). Every transition
writes a `shipment_events` row, retrievable via `/events`.
