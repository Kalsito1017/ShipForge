---
description: Run the PLAN.md section 38 end-to-end demo scenario - release, upload, pipeline, publish, failure injection, AI analysis, retry, success - and narrate each step.
agent: build
---

Run the primary demonstration scenario from PLAN.md §38 as TeamLead.

Verify each step against the running environment (Docker Compose stack must be
up; if not, start with `make dev` and `make migrate`):

1. Create a release (product `demo-service`, version e.g. `1.0.0`)
2. Upload an artifact (`demo-service-1.0.0.tar.gz`) via
   `POST /api/v1/shipments/{id}/artifact`
3. API creates the shipment and queues the worker task (202)
4. Celery processes the shipment
5-8. Validate, Build, Scan run; artifact is published (`PUBLISHED`)
9. Metrics are recorded (`shipments_created_total`,
    `shipment_processing_duration_seconds`, ...)
10. Logs are available and structured (show a sample line with `shipment_id`)
11. Grafana displays the system (note dashboards; open if stack is running)
12. Introduce a controlled failure: product `failure-build`
13. System records the failure (`FAILED`, `error_code`, events)
14. Analyze the failure: `POST /api/v1/shipments/{id}/analyze`
15. AI provides a probable root cause (mock mode without LLM_API_KEY)
16. "Fix" the problem (re-run with a valid product)
17. Retry the shipment: `POST /api/v1/shipments/{id}/retry`
18. Shipment succeeds

Narrate each step with the concrete command/response (curl or httpx) and the
observed state transition. Stop and report at the first step that fails.

Variant: $ARGUMENTS
