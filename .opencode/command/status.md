---
description: Report ShipForge milestone status against PLAN.md - what is done, what is in flight, blockers, and next milestone.
agent: build
---

Report the current status of the ShipForge project as TeamLead.

1. Read `PLAN.md` sections 8-32 (the phase list) and `AGENTS.md`
   (milestone checkpoints).
2. Inspect the repository state: which directories/files exist vs planned
   (`apps/`, `infrastructure/`, `scripts/`, `docs/`, `.github/workflows/`),
   `git log --oneline -15`, `git status --short`.
3. Check verification tooling state: run `make lint`, `make typecheck`,
   `make test` if the targets/dependencies exist; skip gracefully with a note
   if not yet installed.
4. Produce a concise report:
   - Milestones completed (M0-M7) with evidence
   - Work in flight
   - Definition-of-done items (PLAN.md §34) still open
   - Blockers and risks
   - The next milestone and its deliverables

User request: $ARGUMENTS
