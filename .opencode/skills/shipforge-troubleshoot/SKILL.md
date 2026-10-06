---
name: shipforge-troubleshoot
description: Use when investigating ShipForge incidents or writing troubleshooting docs - covers the five incident scenarios (CrashLoopBackOff, database down, stuck shipment, upload failure, ingress issues) with kubectl/compose investigation playbooks. Front-load for incident response and docs/troubleshooting.md work.
---

# ShipForge Troubleshooting Playbook

Systematic investigation for the five documented incident scenarios.

## General first steps

```bash
make status                     # compose ps + kubectl get pods
docker compose logs -f api      # or worker
kubectl get pods,svc,ingress -A
kubectl get events --sort-by=.lastTimestamp
kubectl describe pod <pod>
kubectl logs <pod> [--previous]
```

Structured logs carry `shipment_id`, `stage`, `error_code` — correlate with
`shipment_events` rows in PostgreSQL.

## Scenario 1 — API CrashLoopBackOff

`kubectl describe pod` → check Liveness/Readiness failures, OOMKilled, exit
code; `kubectl logs --previous` for the fatal error; verify config/Secret
env vars, DB reachability, and port alignment.

## Scenario 2 — Database unavailable

Check pod → service → DNS → credentials → connection string: `kubectl get
svc`, `nslookup` from an app pod, `pg_isready` from the postgres pod, compare
`DATABASE_URL` host/user/db with Secret values. Common causes: wrong service
name, missing Secret, migration not applied.

## Scenario 3 — Shipment stuck (not moving state)

Check Redis broker (`redis-cli ping`, `LLEN` queues), Celery worker alive and
consuming (`celery inspect active/reserved`), worker logs for the shipment_id,
DB row status vs expected, and retry counters. A stage exception with retries
exhausted leaves `FAILED`; a lost task may leave a mid-state — inspect
`shipment_events` for the last transition.

## Scenario 4 — Artifact upload fails

Verify MinIO pod/service health, bucket exists, credentials match Secret,
network from api → minio:9000, file size vs `ARTIFACT_MAX_SIZE_MB`, filename
and content-type validation errors in API logs.

## Scenario 5 — Ingress unavailable

`kubectl get ingress` → address empty? check ingress controller running,
Service port vs container port, Ingress backend service name/port, and
readiness probes (failing pods are removed from endpoints).

## Recording findings

For `docs/troubleshooting.md`: symptom → commands → likely causes → fix.
Include expected output snippets so readers can compare.
