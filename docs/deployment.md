# Deployment Guide

ShipForge runs locally in two environments. Both use the same images and the
same Helm chart — only configuration differs.

## 1. Docker Compose (development)

```bash
cp .env.example .env    # set JWT_SECRET; optional LLM_API_KEY
make dev                # postgres, redis, minio, api, worker, prometheus, grafana
make migrate            # first run only: create schema + seed dev users
```

Services:

| Service | URL |
|---|---|
| API | http://localhost:8000 (`/docs` for OpenAPI) |
| MinIO console | http://localhost:9001 (minioadmin/minioadmin) |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 (admin/shipforge) |

Stop: `make dev-down`. Logs: `make logs`. Status: `make status`.

Verify the deployment end to end:

```bash
python3 scripts/smoke_compose.py
./scripts/health-check.sh
```

## 2. kind + Helm (production-like)

### Create the cluster

```bash
make cluster
```

This creates the `shipment-platform` kind cluster
(`infrastructure/kubernetes/kind-config.yaml`), builds the images, loads them
into the cluster and installs the ingress-nginx controller.

> Ingress host ports are `18080`/`18443` (8080 is commonly taken by other
> local services).

### Deploy

```bash
make deploy
```

Runs `helm upgrade --install` with `values-local.yaml`. First deploy also
needs the migration:

```bash
kubectl exec deploy/shipment-platform-shipment-platform-api -- \
  python -m alembic upgrade head
```

### Access

```bash
curl -H "Host: shipforge.local" http://localhost:18080/health
curl -H "Host: shipforge.local" http://localhost:18080/api/v1/shipments
```

Or add `127.0.0.1 shipforge.local` to `/etc/hosts` and use
`http://shipforge.local:18080`.

### Verify

```bash
kubectl get pods
SHIPFORGE_URL=http://localhost:18080 ./scripts/health-check.sh
```

### Upgrade and rollback

```bash
helm upgrade shipment-platform ./infrastructure/helm/shipment-platform \
  --values ./infrastructure/helm/shipment-platform/values-local.yaml \
  --set config.logLevel=DEBUG

helm history shipment-platform
helm rollback shipment-platform <revision>
```

### Teardown

```bash
make undeploy
make cluster-delete
```

## Helm chart

Location: `infrastructure/helm/shipment-platform`.

| Resource | Purpose |
|---|---|
| Deployment (api, worker, redis, prometheus, grafana) | Stateless components |
| StatefulSet (postgres, minio) + PVC | Stateful components |
| Service | ClusterIP for each component |
| Ingress | Host-based routing to the API (`shipforge.local`) |
| ConfigMap / Secret | Non-secret config and credentials |
| ServiceAccount / Role / RoleBinding | Prometheus pod discovery |

Values files: `values.yaml` (defaults), `values-local.yaml` (kind: preloaded
images, `pullPolicy: Never`), `values-dev.yaml`.

Key settings (`values.yaml`):

- `image.api.*` / `image.worker.*` — repository, tag, pullPolicy
- `api.replicas`, `api.resources`, `worker.replicas`, `worker.concurrency`
- `config.*` — app env, log level, LLM endpoint/model
- `secret.*` — local dev credentials (use a secret manager in real clusters)
- `monitoring.enabled` — Prometheus + Grafana stack
- `ingress.host`, `ingress.className`

Raw manifests can be rendered from the chart:

```bash
make manifests   # -> infrastructure/kubernetes/rendered/shipforge.yaml
```

## Production practices included

- **Probes**: readiness + liveness on every workload (HTTP for api/minio,
  `pg_isready` for postgres, `redis-cli ping`, `celery inspect ping` for
  worker)
- **Resources**: requests and limits on all containers
- **Graceful shutdown**: preStop drain on the API, Celery warm shutdown,
  explicit `terminationGracePeriodSeconds`
- **Security context**: non-root (`runAsNonRoot`, fixed UIDs), read-only
  root filesystem where practical, `capabilities.drop: [ALL]`,
  `no-new-privileges`
- **Configuration**: ConfigMap/Secret/environment only — nothing hardcoded

## CI (GitHub Actions)

| Workflow | Triggers | Contents |
|---|---|---|
| `test.yml` | PR, push to main | lint, strict mypy, pytest vs postgres service; full compose integration job |
| `build.yml` | push to main | Docker build + Trivy image scan (CRITICAL/HIGH gate) |
| `security.yml` | PR, push, weekly | pip-audit, Trivy filesystem scan, gitleaks |

Deployment is intentionally local-only; CI validates the project.

## Environment variables

See `.env.example` for the full list. Summary:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Celery broker |
| `MINIO_*` | Artifact storage endpoint and credentials |
| `JWT_SECRET` | Token signing secret (required for auth) |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | AI assistant (optional) |
| `ARTIFACT_MAX_SIZE_MB` | Upload size limit |
| `LOG_LEVEL` / `APP_ENV` | Logging and environment name |

## Troubleshooting

See [troubleshooting.md](troubleshooting.md) for incident runbooks.
