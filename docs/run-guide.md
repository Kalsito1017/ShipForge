# Run Guide — ShipForge on Ubuntu, step by step

A complete, copy-pasteable walkthrough on Ubuntu/WSL. Every step lists the
exact command, what it does, and what output to expect. When you finish you
will have: the platform running, a shipment published through the full
pipeline, a deliberate failure analyzed by the AI and retried, and the
monitoring dashboards open.

**Estimated time**: ~15 minutes (plus image downloads on first run).

```text
Step 1  Prerequisites (apt packages)
Step 2  Get the code
Step 3  Configure secrets (.env)
Step 4  Install Python dependencies
Step 5  Start the platform (Docker Compose)
Step 6  Initialize the database (migrations + seed users)
Step 7  Health check
Step 8  Login and get a token
Step 9  Create a shipment
Step 10 Build and upload an artifact
Step 11 Watch the pipeline publish it
Step 12 Inspect events and download the artifact
Step 13 Prove idempotency (publish is safe to repeat)
Step 14 Inject a failure -> AI analysis -> retry
Step 15 Metrics and Grafana dashboards
Step 16 Run the test suite
Step 17 (Optional) Kubernetes: kind + Helm
Step 18 Stop / clean up
```

---

## Step 1 — Prerequisites (Ubuntu)

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip make curl openssl tar git
```

Verify:

```bash
python3 --version    # 3.12 or newer
make --version
curl --version | head -1
```

Expected:

```text
Python 3.12.x   (or newer)
GNU Make 4.x
curl 8.x
```

**Docker Engine + Compose plugin** (skip if `docker --version` already works):

```bash
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo "deb [arch=$(dpkg --print-architecture) \
signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu \
$(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
```

Allow your user to run Docker without sudo (log out and back in afterwards):

```bash
sudo usermod -aG docker $USER
```

Verify Docker and Compose:

```bash
docker --version
docker compose version
docker run --rm hello-world | head -5
```

Expected:

```text
Docker version 27.x or newer
Docker Compose version v2.x
Hello from Docker!
```

> On WSL2 with Docker Desktop: enable "WSL integration" for your distro in
> Docker Desktop settings, then the same commands work.

## Step 2 — Get the code

```bash
cd ~
git clone <this-repo-url> shipforge
cd shipforge
```

Verify:

```bash
ls
```

Expected: `README.md  PLAN.md  Makefile  docker-compose.yml  apps/  docs/  infrastructure/  scripts/`

## Step 3 — Configure secrets

```bash
cp .env.example .env
```

Generate a strong JWT secret and put it in `.env`:

```bash
SECRET=$(openssl rand -hex 32)
sed -i "s|^JWT_SECRET=.*|JWT_SECRET=${SECRET}|" .env
grep '^JWT_SECRET=' .env
```

Expected: `JWT_SECRET=<64 hex characters>` (never commit this file — `.env`
is gitignored).

Optional: enable the real LLM for the AI assistant (otherwise the built-in
offline mock is used and everything still works):

```bash
sed -i "s|^LLM_API_KEY=.*|LLM_API_KEY=sk-your-key-here|" .env
```

## Step 4 — Install Python dependencies

```bash
make install
```

This creates `.venv/` and installs the API and worker packages with their dev
extras (pytest, ruff, mypy).

Verify:

```bash
.venv/bin/python --version
.venv/bin/python -c "import fastapi, sqlalchemy, celery, minio, jwt, bcrypt; print('deps ok')"
```

Expected: `deps ok`

## Step 5 — Start the platform

```bash
make dev
```

Starts 7 containers: `postgres`, `redis`, `minio`, `api`, `worker`,
`prometheus`, `grafana`. First run downloads images — it may take a few
minutes.

Watch them become healthy:

```bash
docker compose ps
```

Expected (all `healthy` or `Up`):

```text
NAME                IMAGE                    STATUS
shipforge-api-1     shipforge-api            Up (healthy)
shipforge-worker-1  shipforge-worker         Up (healthy)
shipforge-postgres-1 postgres:16-alpine      Up (healthy)
shipforge-redis-1   redis:7-alpine           Up (healthy)
shipforge-minio-1   bitnamilegacy/minio      Up (healthy)
shipforge-prometheus-1 prom/prometheus       Up
shipforge-grafana-1 grafana/grafana          Up
```

If a container is not healthy, check its logs:

```bash
docker compose logs api | tail -20
docker compose logs worker | tail -20
```

## Step 6 — Initialize the database

```bash
make migrate
```

Creates the schema (`shipments`, `shipment_events`, `shipment_logs`, `users`)
and seeds the development users.

Verify directly in PostgreSQL:

```bash
docker compose exec -T postgres psql -U shipment -d shipment \
  -c "SELECT username, role FROM users;"
```

Expected:

```text
      username      |      role
--------------------+-----------------
 developer          | developer
 release_manager    | release_manager
 admin              | admin
```

## Step 7 — Health check

```bash
curl -s localhost:8000/health; echo
curl -s localhost:8000/ready; echo
```

Expected: `{"status":"ok"}` twice.

Full check (API + service status):

```bash
./scripts/health-check.sh
```

## Step 8 — Login and get a token

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/v1/auth/login \
  -H 'content-type: application/json' \
  -d '{"username":"admin","password":"admin"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

echo "${TOKEN:0:40}..."
```

Expected: a line starting with `eyJ...` (a JWT).

Check who you are:

```bash
curl -s -H "Authorization: Bearer $TOKEN" localhost:8000/api/v1/auth/me
```

Expected: `{"id":"...","username":"admin","role":"admin"}`

> Seeded users (dev only): `developer/developer`, `release_manager/release_manager`,
> `admin/admin`. Try `developer` — retry/publish will return `403`.

## Step 9 — Create a shipment

```bash
SID=$(curl -s -X POST localhost:8000/api/v1/shipments \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"product":"payment-service","version":"2.4.1"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

echo "shipment id: $SID"
```

Expected: `shipment id: <uuid>` and HTTP 202 (accepted — processing is
asynchronous).

Check it:

```bash
curl -s -H "Authorization: Bearer $TOKEN" localhost:8000/api/v1/shipments/$SID \
  | python3 -m json.tool
```

Expected: `"status": "CREATED"` — the pipeline waits for an artifact.

## Step 10 — Build and upload an artifact

Create a small release tarball (any `.tar.gz` works):

```bash
mkdir -p /tmp/demo
cat > /tmp/demo/main.py <<'EOF'
def charge(amount: float) -> float:
    return amount * 1.0

if __name__ == "__main__":
    print("payment-service", charge(10.0))
EOF

tar -czf /tmp/demo/payment-service-2.4.1.tar.gz -C /tmp/demo main.py
ls -l /tmp/demo/payment-service-2.4.1.tar.gz
```

Upload it:

```bash
curl -s -X POST "localhost:8000/api/v1/shipments/$SID/artifact" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/demo/payment-service-2.4.1.tar.gz;type=application/gzip" \
  | python3 -m json.tool
```

Expected: HTTP 202, `"queued": true`, and artifact metadata with a `sha256`
checksum.

## Step 11 — Watch the pipeline publish it

```bash
for i in $(seq 1 30); do
  STATUS=$(curl -s -H "Authorization: Bearer $TOKEN" \
    localhost:8000/api/v1/shipments/$SID \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')
  echo "[$i] status: $STATUS"
  case "$STATUS" in PUBLISHED|FAILED) break ;; esac
  sleep 1
done
```

Expected output (the pipeline runs Validate → Build → Scan → Publish):

```text
[1] status: CREATED
[2] status: PUBLISHED
```

The shipment is now `PUBLISHED` with a `published_at` timestamp.

## Step 12 — Inspect events and download the artifact

The full audit trail:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  localhost:8000/api/v1/shipments/$SID/events | python3 -m json.tool
```

Expected events (in order):

```text
CREATED -> ARTIFACT_UPLOADED -> PIPELINE_STARTED -> STAGE_COMPLETED (x3) -> PUBLISHED
```

Download the published artifact and verify its checksum:

```bash
curl -s -D /tmp/demo/headers.txt -o /tmp/demo/downloaded.tar.gz \
  -H "Authorization: Bearer $TOKEN" \
  localhost:8000/api/v1/shipments/$SID/artifact

grep -i x-artifact /tmp/demo/headers.txt
sha256sum /tmp/demo/payment-service-2.4.1.tar.gz /tmp/demo/downloaded.tar.gz
```

Expected: identical SHA-256 hashes for both files.

## Step 13 — Prove idempotency

Publishing an already-published shipment is safe:

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  localhost:8000/api/v1/shipments/$SID/publish \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["status"], d["published_at"])'
```

Expected: `PUBLISHED <timestamp>` — unchanged. Count the publish events:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  localhost:8000/api/v1/shipments/$SID/events \
  | python3 -c 'import json,sys; e=json.load(sys.stdin); print("PUBLISHED events:", sum(1 for x in e if x["event_type"]=="PUBLISHED"))'
```

Expected: `PUBLISHED events: 1` — never published twice.

## Step 14 — Inject a failure, analyze with AI, retry

ShipForge ships with deterministic failure products for demos:

| Product | Fails in | Error code |
|---|---|---|
| `failure-validation` | Validate | `VALIDATION_ERROR` |
| `failure-build` | Build | `BUILD_FAILED` |
| `failure-scan` | Scan | `SCAN_FAILED` |
| `failure-timeout` | Validate | `TIMEOUT` |

Create a shipment that must fail:

```bash
FID=$(curl -s -X POST localhost:8000/api/v1/shipments \
  -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"product":"failure-build","version":"1.0.0"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

curl -s -X POST "localhost:8000/api/v1/shipments/$FID/artifact" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/demo/payment-service-2.4.1.tar.gz;type=application/gzip" > /dev/null

sleep 3
curl -s -H "Authorization: Bearer $TOKEN" localhost:8000/api/v1/shipments/$FID \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["status"], d["error_code"], "|", d["error_message"])'
```

Expected: `FAILED BUILD_FAILED | Simulated build failure`

Ask the AI incident assistant to analyze it:

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  localhost:8000/api/v1/shipments/$FID/analyze | python3 -m json.tool
```

Expected (mock mode):

```json
{
  "analysis": {
    "category": "BUILD",
    "root_cause": "The build stage failed while compiling or assembling the artifact...",
    "confidence": 0.8,
    "severity": "MEDIUM",
    "recommendations": ["Review the build stage logs for the first failing step.", ...]
  },
  "source": "mock",
  "advisory": true
}
```

Retry it (needs `release_manager` or `admin`):

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" \
  localhost:8000/api/v1/shipments/$FID/retry \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])'
```

Expected: `VALIDATING` (HTTP 202). `failure-build` fails again by design —
that is its purpose. To see a retry *succeed*, upload a normal product
(repeat Steps 9–11) and retry that one the same way.

Verify the error trail for the failed shipment:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  localhost:8000/api/v1/shipments/$FID/events \
  | python3 -c 'import json,sys; [print(e["event_type"], "-", e["message"]) for e in json.load(sys.stdin)]'
```

## Step 15 — Metrics and dashboards

Application metrics (Prometheus format):

```bash
curl -s localhost:8000/metrics | grep shipments_
curl -s localhost:9100/metrics | grep -E "worker_tasks_total|shipment_queue_size"
```

Query Prometheus:

```bash
curl -s 'localhost:9090/api/v1/query?query=sum(shipments_published_total)' \
  | python3 -m json.tool
```

Open Grafana in a browser:

```text
http://localhost:3000      (admin / shipforge)
```

Go to **Dashboards → ShipForge → ShipForge Overview**. You should see the
shipments you created under "Shipments Published" and the failed one under
"Shipments Failed".

Logs (JSON, with `shipment_id` / `stage` / `error_code`):

```bash
docker compose logs -f api worker
```

## Step 16 — Run the test suite

```bash
make test
```

Expected: `157 passed`. The suite uses its own database (`shipment_test`) —
it is safe to run while the platform is up.

```bash
make lint        # ruff — expect "All checks passed!"
make typecheck   # strict mypy — expect "Success: no issues found in 60 source files"
```

One-command end-to-end verification of everything above:

```bash
python3 scripts/smoke_compose.py
```

Expected: `COMPOSE SMOKE OK` (login → create → upload → publish → failure →
retry → AI analyze).

## Step 17 (Optional) — Kubernetes: kind + Helm

A production-like local cluster (probes, resource limits, ingress). Install
the tools:

```bash
# kubectl
curl -fsSLo /tmp/kubectl "https://dl.k8s.io/release/$(curl -fsSL \
  https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install /tmp/kubectl /usr/local/bin/kubectl

# kind
curl -fsSLo /tmp/kind https://kind.sigs.k8s.io/dl/latest/kind-linux-amd64
sudo install /tmp/kind /usr/local/bin/kind

# helm
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

kubectl version --client && kind version && helm version --short
```

Create the cluster (builds images, loads them into kind, installs ingress):

```bash
make cluster
```

Deploy:

```bash
make deploy
kubectl exec deploy/shipment-platform-shipment-platform-api -- \
  python -m alembic upgrade head
kubectl get pods
```

Expected: 5 pods, all `1/1 Running` (api, worker, postgres, redis, minio).

Access through the ingress (host ports are **18080/18443**):

```bash
SHIPFORGE_URL=http://localhost:18080 ./scripts/health-check.sh
curl -H "Host: shipforge.local" http://localhost:18080/health
```

To repeat the whole demo against Kubernetes, use the same commands as above
but call the API like this:

```bash
curl -H "Host: shipforge.local" -H "Authorization: Bearer $TOKEN" \
  http://localhost:18080/api/v1/shipments
```

Teardown:

```bash
make undeploy
make cluster-delete
```

## Step 18 — Stop / clean up

```bash
make dev-down            # stop the stack (data volumes are kept)
docker compose down -v   # stop and DELETE all data
make clean               # remove python caches
rm -rf /tmp/demo         # remove the demo artifacts
```

---

## When something breaks

```bash
make status                    # compose + kubectl overview
docker compose logs -f api     # JSON logs
./scripts/health-check.sh      # quick liveness/readiness probe
```

See [`troubleshooting.md`](troubleshooting.md) — five incident runbooks plus
the real incidents from this build (each with the exact commands that found
them).

Common quick fixes:

| Symptom | Fix |
|---|---|
| `make dev` fails pulling `minio/minio` | The compose file already uses `bitnamilegacy/minio` — pull again |
| Port 8000 busy | `sudo lsof -i :8000` and stop that process, or edit `docker-compose.yml` |
| `401 Unauthorized` | Token expired — repeat Step 8 |
| `JWT_SECRET` empty | Repeat Step 3 (auth refuses to run without it) |
| Migration error `relation already exists` | `docker compose exec -T postgres psql -U shipment -d shipment -c 'DROP TABLE users;'` then `make migrate` |
| Shipments stuck in `CREATED` | Upload an artifact (Step 10) — the pipeline waits for it |
