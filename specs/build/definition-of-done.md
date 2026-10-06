---
type: Checklist
title: Definition of done
description: The checklist every task and change proposal must satisfy before it is committed.
status: stable
tags: [build, quality, sdd]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

* [ ] The governing specs describe the behavior that was built (spec edited first if needed).
* [ ] New/changed acceptance criteria have IDs; tests cite them (`Covers: XX-NN`).
* [ ] `python scripts/spec_check.py` passes.
* [ ] Backend: `uv run pytest` passes (from `apps/api`).
* [ ] Web: `npm run build` passes (from `apps/web`) when web code changed.
* [ ] No secrets, real PHI or real member data in code, specs, fixtures or logs.
* [ ] `specs/log.md` has a dated entry; the CP's `cp_state` and the task plan status are updated.
* [ ] Specs and code are in the same commit/PR; message references the CP (e.g. `CP-0002: ...`) or carries `[no-spec]` with a reason.
