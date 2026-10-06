---
description: Run a full security and code review sweep of ShipForge using the security and backend reviewers, then summarize findings.
agent: build
---

Run a review sweep of the ShipForge codebase as TeamLead.

1. Dispatch the `security` subagent with a full review brief (its checklist
   covers secrets, authz, input validation, error safety, containers,
   dependencies, AI advisory-only constraints).
2. Dispatch the `backend` subagent in review-only mode for code quality:
   type hints, Pydantic coverage, exception handling, idempotency correctness,
   state-machine compliance, test gaps.
3. If infrastructure files exist, dispatch `devops` for a container/K8s/CI
   review (non-root, probes, limits, secrets handling, workflow hygiene).
4. Consolidate all findings into one report ordered by severity:
   `file:line`, issue, remediation, and the agent who should fix it.
5. Ask the user which findings to fix now, if any.

Review focus (optional): $ARGUMENTS
