---
description: Implement an accepted change proposal against the specs, with tests citing acceptance IDs, then prepare one commit.
argument-hint: CP-NNNN
---

Implement change proposal $ARGUMENTS.

1. Open `specs/changes/` and find the CP. If its `cp_state` is not `accepted`, stop and say so.
2. Read the CP and every spec it links. The specs are the source of truth; if you find a gap or contradiction, stop and propose a spec edit instead of guessing.
3. Work the CP's task list in order. For each task:
   * write or update tests whose docstrings cite the acceptance IDs (`Covers: XX-NN`);
   * implement the code (module docstrings cite governing specs);
   * run `cd apps/api && uv run pytest` (and `cd apps/web && npm run build` for web changes).
4. Close out: set touched specs to `status: stable`, the CP to `cp_state: implemented`, update `specs/build/task-plan.md` if relevant, and add a dated entry to `specs/log.md`.
5. Run `python scripts/spec_check.py`.
6. Stage specs and code together and propose a commit message starting with the CP id. Report test results honestly, including failures.
