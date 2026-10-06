---
description: Draft a change proposal and the spec edits for a change, then stop for human review (no code).
argument-hint: <describe the change>
---

You are starting a spec-driven change. The requested change is:

$ARGUMENTS

Follow `specs/process/sdd-workflow.md`:

1. Read `specs/index.md`, then every spec the change touches (follow links). Identify affected concepts, acceptance IDs and prompts.
2. Pick the next free CP number from `specs/changes/index.md`. Create `specs/changes/cp-NNNN-<slug>.md` from `specs/process/change-proposal-template.md` with `cp_state: proposed`: why, what changes, affected specs, new/changed acceptance criteria (new IDs, never reuse), tasks, risks, out of scope.
3. Edit the affected specs directly (set their `status: draft`), add/modify acceptance criteria, update prompts if behavior changes, and add the CP to `specs/changes/index.md`.
4. Add a dated entry to `specs/log.md`.
5. Run `python scripts/spec_check.py` and fix any issues.
6. **Do not write or change application code.** Finish by summarizing the CP, the spec diff (`git diff --stat specs/`), open questions, and ask the human to review and set `cp_state: accepted`.
