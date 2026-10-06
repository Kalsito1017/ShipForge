# Troubleshooting

Runbooks for the five common incident scenarios plus real incidents observed
during development — with the commands that found them.

## Quick triage

```bash
make status                                  # compose + kubectl
docker compose logs -f api worker            # or: kubectl logs deploy/<name>
./scripts/health-check.sh                    # health, ready, API probe
kubectl get pods                             # STATUS / RESTARTS columns
kubectl get events --sort-by=.lastTimestamp
```

Correlate with the shipment event trail:

```bash
curl -H "Authorization: Bearer $TOKEN" \
  localhost:8000/api/v1/shipments/<id>/events
```

Structured logs carry `shipment_id`, `stage`, `error_code` — filter on those.

---

## Scenario 1 — API CrashLoopBackOff

**Symptom**: `kubectl get pods` shows `CrashLoopBackOff` and rising RESTARTS
for the api pod.

**Investigate**:

```bash
kubectl describe pod <api-pod>        # Last State, Exit Code, probe failures
kubectl logs <api-pod> --previous     # the fatal error before the restart
```

**Likely causes and fixes**:

| Cause | Evidence | Fix |
|---|---|---|
| Import/config error at startup | Traceback in `logs --previous` | Fix the code; rebuild and load the image |
| Missing env (e.g. `DATABASE_URL`) | `KeyError`/`OperationalError` on boot | Check ConfigMap/Secret keys |
| Database unreachable | `/ready` 503 loop | See Scenario 2 |
| OOMKilled | Exit Code 137, `Reason: OOMKilled` | Raise memory limits in values |

Real incident from this build: the worker was **OOMKilled** at 256Mi because
Celery prefork needs headroom — raised to 512Mi and it stabilized.

## Scenario 2 — Database unavailable

**Symptom**: `/ready` returns 503; API logs show connection errors.

**Investigate** (pod → service → DNS → credentials → connection string):

```bash
kubectl get pods,svc | grep postgres
kubectl exec deploy/<api> -- python -c "import os; print(os.environ['DATABASE_URL'])"
kubectl exec deploy/<postgres> -- pg_isready -U shipment -d shipment
```

**Likely causes and fixes**:

| Cause | Evidence | Fix |
|---|---|---|
| Wrong service name in URL | URL host ≠ Service name | Align `DATABASE_URL` with the service name |
| Bad credentials | `password authentication failed` | Check Secret keys |
| Migration not applied | `relation "shipments" does not exist` | `alembic upgrade head` |
| Env var expansion order | Empty user/db in the URL | See real incident below |

Real incident from this build: `DATABASE_URL` used `$(POSTGRES_USER)` **before**
that variable was defined in the pod spec. Kubernetes only expands variables
defined earlier, so the URL resolved with empty credentials and `/ready` never
passed. Fix: define the source variables before `DATABASE_URL`.

Real incident (dev DB): a test helper's `drop_all` wiped the migration-managed
schema — `relation "shipments" does not exist` on the next request. Fix:
`alembic upgrade head`; tests now use a separate `shipment_test` database.

## Scenario 3 — Shipment stuck

**Symptom**: a shipment stays in `CREATED`/`VALIDATING`/… and never reaches a
terminal state.

**Investigate** (Redis → Celery → worker → DB):

```bash
curl -s localhost:9100/metrics | grep shipment_queue_size
docker compose logs worker | grep <shipment_id>
docker compose exec redis redis-cli llen celery
```

Check the last event and the worker's view:

```sql
SELECT event_type, message, created_at FROM shipment_events
WHERE shipment_id = '<id>' ORDER BY created_at;
SELECT status, error_code FROM shipments WHERE id = '<id>';
```

**Likely causes and fixes**:

| Cause | Evidence | Fix |
|---|---|---|
| Worker down | No worker log lines; queue growing | Restart worker; check its logs |
| Task never dispatched | No `PIPELINE_STARTED` event | Call `POST /shipments/{id}/retry` |
| Awaiting artifact | `outcome: awaiting_artifact` in logs | Upload the artifact (re-dispatches) |
| Failed but not retried | status `FAILED` with `error_code` | Fix cause, then `POST /{id}/retry` |
| Redis misconfigured | Worker logs show broker errors | See real incident below |

Real incident from this build: Redis ran with a **read-only root filesystem**
but tried to persist RDB snapshots → `MISCONF … stop-writes-on-bgsave-error`,
which killed the worker's broker connection and left tasks stuck. Fix: run the
broker persistence-free (`--save "" --appendonly no`).

## Scenario 4 — Artifact upload fails

**Symptom**: `POST /shipments/{id}/artifact` returns 4xx/5xx.

**Investigate** (API → MinIO → credentials → bucket → network):

```bash
docker compose logs api | tail -20
docker compose ps minio
curl -s localhost:9000/minio/health/live
```

**Likely causes and fixes**:

| Cause | HTTP | Fix |
|---|---|---|
| Bad filename/content type | 400 `ARTIFACT_INVALID_TYPE` | Use `.tar.gz`/`.tgz`/`.zip`, safe name |
| Too large | 400 `ARTIFACT_TOO_LARGE` | Raise `ARTIFACT_MAX_SIZE_MB` or shrink |
| Corrupt/empty archive | 400 `VALIDATION_ERROR` | Repack the artifact |
| Shipment not uploadable | 409 | Only `CREATED`/`FAILED` accept uploads |
| Storage unreachable | 500 `INTERNAL_ERROR` | Check MinIO health, credentials, `MINIO_ENDPOINT` |

Real incident from this build: MinIO refused to start
(`Unable to initialize backend: file access denied`) because the volume was
root-owned while the container runs as uid 1001. Fix: `fsGroup: 1001` in the
pod security context (or a chown init container where fsGroup is not enough).

## Scenario 5 — Ingress unavailable

**Symptom**: `curl http://localhost:18080` fails or returns 503, while the API
is healthy inside the cluster.

**Investigate** (pod → service → ingress → port):

```bash
kubectl get ingress
kubectl get endpoints <api-service>
kubectl get pods -n ingress-nginx
kubectl describe ingress <name>
```

**Likely causes and fixes**:

| Cause | Evidence | Fix |
|---|---|---|
| Ingress controller not running | No pods in `ingress-nginx` | `make cluster` installs it; re-run |
| Wrong Host header | Ingress rule has `host: shipforge.local` | Use `-H "Host: shipforge.local"` |
| Host port conflict | `Bind for 0.0.0.0:8080 failed` at cluster create | Chart uses 18080/18443; free the port or change `kind-config.yaml` |
| API not ready | Empty endpoints | Fix readiness (Scenarios 1–2) |
| Wrong service port | Ingress backend ≠ service port | Check `values.yaml` `api.port` |

Real incident from this build: port 8080 was already taken by another local
container, so the kind node could not bind the ingress ports. Fix: move the
mapping to 18080/18443 in `infrastructure/kubernetes/kind-config.yaml`.

---

## Real incidents: observability

### Worker metrics all zero

The worker's metrics endpoint returned 0 for every counter even though the
pipeline was publishing.

**Cause**: the Docker/Kubernetes healthcheck (`celery inspect ping`) imported
the worker entrypoint, and a module-level `shutil.rmtree` in the metrics
bootstrap wiped the live metrics directory on **every healthcheck** (every
15s). The workers kept writing to deleted files.

**Fix**: wipe only once at real worker startup; the healthcheck path is now
side-effect free. **Lesson**: never put destructive side effects in module
import — auxiliary processes import the same modules.

### Celery signals silently not firing

Task counters and JSON logs were no-ops.

**Cause**: `signal.connect(receiver)` defaults to `weak=True`; the local
closure was garbage-collected before the signal fired.

**Fix**: `connect(receiver, weak=False)`.

### Duplicate publications (race)

Two `PUBLISHED` events 18ms apart for one shipment.

**Cause**: `POST /shipments` and the artifact upload both dispatch the
pipeline; two tasks ran concurrently in the prefork pool, both read `READY`
and both published.

**Fix**: `SELECT … FOR UPDATE` at pipeline entry and in publish/retry paths —
concurrent runs serialize. **Lesson**: status checks without a lock are not
safety guarantees under concurrency.

### Tests interfering with the live stack

Flaky test failures and wiped dev users.

**Cause**: tests shared the development database; teardown deleted all rows.

**Fix**: tests use a dedicated `shipment_test` database, auto-created. Suite
and live smoke now run concurrently without interference.

---

## Metrics and logs cheat sheet

```bash
curl -s localhost:8000/metrics | grep shipments_
curl -s localhost:9100/metrics | grep worker_
curl -s "localhost:9090/api/v1/query?query=sum(shipments_failed_total)"
docker compose logs api | python3 -c "import json,sys; [print(json.loads(l.split('| ',1)[1])) for l in sys.stdin if l.strip().endswith('}')]"
```

Grafana dashboards: `http://localhost:3000` → Dashboards → ShipForge.

## AI incident analysis

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  localhost:8000/api/v1/shipments/<id>/analyze
```

Returns a category/root-cause/severity diagnosis and recommendations. It is
advisory only — if it looks wrong, trust the event trail and logs over the
suggestion.
