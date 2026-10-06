# Security

ShipForge is a local platform, but it is built with production security
practices. This document describes the controls in place and the deliberate
limitations of a local setup.

## Authentication & authorization

- **JWT bearer tokens** (HS256) via `POST /api/v1/auth/login`.
  `JWT_SECRET` comes from the environment — never from git. Startup refuses to
  authenticate if the secret is empty.
- **Password hashing**: bcrypt with per-password salts. Passwords are never
  stored, logged or returned. Verification is constant-time.
- **Roles**: `developer`, `release_manager`, `admin` with an explicit
  permission table (`app/core/auth.py`). Every protected endpoint declares a
  required permission; missing permission → `403`.
- **No user enumeration**: unknown user and wrong password return the same
  `401` error.
- **Token hygiene**: expiry enforced (`JWT_EXPIRES_MINUTES`), tampered and
  expired tokens rejected with `401`, disabled users cannot authenticate.

## Input validation

- All request bodies/params validated with Pydantic (types, lengths, regex
  patterns for product/version).
- **Artifact uploads**: filename allowlist (no path separators or traversal),
  content-type allowlist, size limit (`ARTIFACT_MAX_SIZE_MB`), archive
  integrity check. Storage paths are derived only from validated components.
- Invalid input returns `422`/`400` with a safe error envelope.

## Error handling

- Uniform error envelope `{"error": {"code", "message"}}`.
- Internal details (stack traces, SQL, hostnames) never reach clients; they go
  to structured logs only.
- Unhandled exceptions map to a generic `INTERNAL_ERROR`.

## Data access

- SQLAlchemy with bound parameters — no string-built SQL anywhere.
- Database credentials via environment (`DATABASE_URL`), not source code.

## Secrets management

- `.env` is gitignored; only `.env.example` (placeholders) is committed.
- CI runs gitleaks and Trivy secret scanning to catch accidental commits.
- Kubernetes: credentials in `Secret` resources (local dev values; use a real
  secret manager for production clusters).

## Container & cluster hardening

- Images: multi-stage, minimal `python:3.12-slim`, pinned dependencies
  (`requirements.lock`), non-root user (`uid 10001`).
- Compose/Kubernetes: `read_only` rootfs (+ `/tmp` tmpfs where needed),
  `capabilities.drop: [ALL]`, `no-new-privileges`, resource requests/limits.
- Dependency and image scanning in CI: pip-audit, Trivy (CRITICAL/HIGH gate).

## AI assistant constraints

The incident assistant (`POST /api/v1/shipments/{id}/analyze`) is **advisory
only**:

- It returns text recommendations for a human operator.
- It has **no** ability to execute commands, modify infrastructure, delete
  artifacts, or deploy.
- LLM output is validated with Pydantic before it is returned; malformed
  responses are rejected and the mock fallback is used.
- Request timeouts are enforced (`LLM_TIMEOUT_SECONDS`).
- Context sent to the LLM contains no secrets (operational facts only).

## Timeouts & availability

- LLM calls have a hard timeout.
- HTTP probes (readiness/liveness) fail fast on unavailability.
- Celery retries are bounded; idempotency prevents duplicate publication even
  under retries.

## Known limitations (local platform)

These are acceptable for a local demonstration platform and should be
addressed before any real deployment:

| Area | Local state | Production expectation |
|---|---|---|
| Secrets | `.env` / Helm values files | External secret manager (Vault, KMS) |
| TLS | Plain HTTP on localhost | TLS everywhere, HSTS |
| Token revocation | Expiry only | Short-lived tokens + refresh/revocation |
| Rate limiting | None | Per-user/IP rate limits |
| RBAC | Three fixed roles | Fine-grained, externally managed |
| User management | Seeded users | Provisioning flow, MFA |
| Postgres/Redis/MinIO auth | Dev credentials | Managed services, least privilege |
| Audit | Event trail in DB | Centralized audit log, tamper evidence |

## Verifying the security posture

```bash
make lint && make typecheck && make test   # safe errors, role matrix tests
pip-audit                                   # dependency vulnerabilities
trivy fs .                                  # filesystem + secret scan
trivy image shipforge-api:local             # image scan
```

See `docs/api.md` for the permission matrix and error codes.
