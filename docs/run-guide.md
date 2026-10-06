# Run Guide — ShipForge from zero to demo

A step-by-step walkthrough: start the platform, run a shipment through the
full pipeline, inject a failure, retry it, and inspect the result in metrics,
logs and Grafana. Every command is copy-pasteable.

There are two ways to run ShipForge. **Use Option A first** (Docker Compose).
Option B (Kubernetes) is the production-like environment.

---

## 1. Prerequisites

```bash
python3 --version      # 3.12+
docker --version       # Docker + Compose
make --version
```

Only for Option B (Kubernetes): `kubectl`, `kind`, `helm`.

## 2. Configure

```bash
git clone <this-repo> shipforge
cd shipforge

cp .env.example .env
```

Edit `.env` and set at least:

```text
JWT_SECRET=<openssl rand -hex 32>
```

Optional — only if you want the real LLM (otherwise the offline mock is used):

```text
LLM_API_KEY=<your key>
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
```

## 3. Start the platform (Option A — Docker Compose)

```bash
make install     # Python deps into .venv
make dev         # postgres, redis, minio, api, worker, prometheus, grafana
make migrate     # schema + seeded users (first run)
```

Check everything is healthy:

```bash
make status
./scripts/health-check.sh
```

Expected: `OK health`, `OK ready`, `OK shipments`, and all containers healthy.

| Service | URL |
|---|---|
| API (OpenAPI docs) | http://localhost:8000/docs |
| MinIO console | http://localhost:9001 (minioadmin / minioadmin) |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 (admin / shipforge) |

## 4. Get an API token

Seeded development users (change these for anything real):

| User | Password | Role |
|---|---|---|
| `developer` | `developer` | create/read/upload/analyze |
| `release_manager` | `release_manager` | + retry/publish |
| `admin` | `admin` | everything |

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"username":"admin","password":"admin"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

curl -s -H "Authorization: Bearer $TOKEN" localhost:8000/api/v1/auth/me
```

## 5. Run a shipment end to end

**5a. Create the shipment** (returns 202 — processing is asynchronous):

```bash
SID=$(curl -s -X POST localhost:8000/api/v1/shipments \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"product":"demo-service","version":"1.0.0"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

echo "shipment: $SID"
```

**5b. Create and upload an artifact:**

```bash
mkdir -p /tmp/demo && echo 'print("ship me")' > /tmp/demo/main.py
tar -czf /tmp/demo/demo-service-1.0.0.tar.gz -C /tmp/demo main.py

curl -s -X POST "localhost:8000/api/v1/shipments/$SID/artifact" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/demo/demo-service-1.0.0.tar.gz;type=application/gzip"
```

**5c. Watch the pipeline** (Validate → Build → Scan → Publish):

```bash
curl -s -H "Authorization: Bearer $TOKEN" localhost:8000/api/v1/shipments/$SID
```

Repeat until `status` is `PUBLISHED` (usually a few seconds). The full event
trail:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  localhost:8000/api/v1/shipments/$SID/events | python3 -m json.tool
```

**5d. Download the published artifact** (checksum header included):

```bash
curl -s -D - -o /tmp/demo/out.tar.gz \
  -H "Authorization: Bearer $TOKEN" \
  localhost:8000/api/v1/shipments/$SID/artifact | grep -i x-artifact
```

## 6. Prove idempotency

Publishing again is safe — no second publication:

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  localhost:8000/api/v1/shipments/$SID/publish
```

Still `PUBLISHED`, exactly one `PUBLISHED` event in the trail.

## 7. Inject a failure and fix it

Deterministic failure products: `failure-validation`, `failure-build`,
`failure-scan`, `failure-timeout`.

```bash
FID=$(curl -s -X POST localhost:8000/api/v1/shipments \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"product":"failure-build","version":"1.0.0"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

curl -s -X POST "localhost:8000/api/v1/shipments/$FID/artifact" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/demo/demo-service-1.0.0.tar.gz;type=application/gzip"

curl -s -H "Authorization: Bearer $TOKEN" localhost:8000/api/v1/shipments/$FID
# -> status FAILED, error_code BUILD_FAILED
```

**Analyze with the AI assistant** (advisory only):

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  localhost:8000/api/v1/shipments/$FID/analyze | python3 -m json.tool
```

**Retry** (needs `release_manager` or `admin`):

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  localhost:8000/api/v1/shipments/$FID/retry
```

`failure-build` keeps failing by design (that is its job). To see a retry
succeed, create a normal product shipment and retry it the same way.

## 8. Look at the observability stack

```bash
curl -s localhost:8000/metrics | grep shipments_
curl -s localhost:9100/metrics | grep worker_
```

- Grafana: http://localhost:3000 (admin / shipforge) → Dashboards →
  **ShipForge Overview**
- Prometheus: http://localhost:9090 — try `sum(shipments_published_total)`
- Logs: `docker compose logs -f api worker` (JSON lines)

## 9. One-command verification

The whole flow above (plus failure + retry + analyze) in one script:

```bash
python3 scripts/smoke_compose.py
```

## 10. Stop / clean up

```bash
make dev-down       # stop the stack (data volumes kept)
docker compose down -v   # stop and delete all data
make clean          # remove build/test caches
```

---

## Option B — Kubernetes (kind + Helm)

Production-like: same images, real Kubernetes with probes, limits, ingress.

```bash
make cluster        # create kind cluster, build+load images, install ingress
make deploy         # helm upgrade --install (values-local.yaml)

# first deploy only: run the migration
kubectl exec deploy/shipment-platform-shipment-platform-api -- \
  python -m alembic upgrade head

kubectl get pods    # wait until all 5 are 1/1 Ready
```

Access through the ingress (host header required; host ports 18080/18443):

```bash
SHIPFORGE_URL=http://localhost:18080 ./scripts/health-check.sh

curl -H "Host: shipforge.local" http://localhost:18080/health
```

Run the full demo against Kubernetes with any of the steps above — just
replace `localhost:8000` with `-H "Host: shipforge.local" http://localhost:18080`
and add the auth header as usual.

Upgrade and rollback:

```bash
helm upgrade shipment-platform ./infrastructure/helm/shipment-platform \
  --values ./infrastructure/helm/shipment-platform/values-local.yaml \
  --set config.logLevel=DEBUG
helm history shipment-platform
helm rollback shipment-platform <revision>
```

Teardown:

```bash
make undeploy
make cluster-delete
```

---

## Testing and checks

```bash
make test           # 157 tests (uses its own shipment_test database)
make lint
make typecheck
```

The suite is safe to run while the platform is up — tests never touch the dev
stack or its data.

## When something breaks

See [troubleshooting.md](troubleshooting.md) — five incident runbooks plus the
real incidents from this build. Quick triage:

```bash
make status
docker compose logs -f api worker
./scripts/health-check.sh
```
