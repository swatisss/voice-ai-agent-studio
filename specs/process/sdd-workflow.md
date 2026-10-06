---
type: Process
title: Spec-driven development workflow
description: The loop every change follows in this repo - change proposal, spec edits, review, implementation, verification - with specs and code shipped together.
status: stable
tags: [process, sdd]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Principles

1. **Specs are the source of truth.** The `specs/` folder (an [OKF](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) v0.2 bundle) defines *what* the system does and *why*. Code defines *how*. When they disagree, the spec wins until a spec change says otherwise.
2. **Spec first, then code.** Any change in behavior, contract, data model, prompt or UI starts as a spec edit. Code is written only against specs.
3. **Specs and code ship together.** The commit (or PR) that changes behavior contains both the spec edit and the code. Spec-only commits are fine; behavior-changing code-only commits are not.
4. **Everything testable has an ID.** Acceptance criteria carry IDs (e.g. `ESC-03`). Tests cite the IDs they cover, so a spec line can be traced to the code and test that satisfy it.
5. **Humans review specs, agents write code.** The most valuable review is of the spec diff. Code review checks the code satisfies the spec.
6. **Prompts are specs.** LLM prompts live in [/prompts](/prompts/) and are loaded or mirrored by code verbatim; changing agent behavior by editing a prompt is a spec change.

# The loop

```
 idea / bug / feedback
        │
        ▼
 1. Change proposal  specs/changes/cp-NNNN-slug.md   (cp_state: proposed)
        │            why, what changes, affected specs, acceptance IDs, tasks
        ▼
 2. Spec edits       update the affected concept files (status: draft while in flux)
        │            add/modify acceptance criteria; never reuse old IDs
        ▼
 3. Review           human reads the spec diff; adds `verified` to reviewed files
        │            CP → cp_state: accepted
        ▼
 4. Implement        coding agent works the CP's task list against the specs
        │            tests reference acceptance IDs
        ▼
 5. Verify           `python scripts/spec_check.py` + backend tests + web build
        │
        ▼
 6. Close            specs → status: stable, CP → cp_state: implemented,
                     entry in specs/log.md, single commit/PR with specs + code
```

# What needs a change proposal

| Change | CP needed? | What to do |
|---|---|---|
| New feature, new page, new API field, data model change | Yes | Full loop |
| Prompt change that alters agent behavior | Yes | Full loop; include before/after examples |
| Bug where code violates an existing acceptance criterion | No | Fix code, add/repair the test citing the ID, commit with `[no-spec]` and `fixes ESC-03` |
| Bug where the spec itself was wrong or silent | Yes (small CP is fine) | Fix the spec first, then the code |
| Typo, clarification, link fix in specs | No | Edit + `log.md` entry |
| Refactor, dependency bump, tooling with no behavior change | No | Commit with `[no-spec]` |

# Working with a coding agent (Claude Code)

* `/spec-change <idea>` — the agent drafts a CP and the spec edits, then **stops** for your review. It does not write code.
* You review `git diff specs/`, edit as needed, and set `cp_state: accepted`.
* `/spec-implement CP-0002` — the agent implements the CP tasks, writes tests for the acceptance IDs, runs the checks, updates `log.md`, flips states, and prepares one commit.
* Agents read `AGENTS.md` at the repo root (outside this bundle) for commands and rules.

# Guardrails (automated)

`scripts/spec_check.py` runs as a git hook (`.githooks/`) and in CI:

* **OKF lint** — every non-reserved `.md` under `specs/` has YAML frontmatter with a non-empty `type`; reserved `index.md`/`log.md` have no frontmatter except the root `okf_version`.
* **Index coverage** — every concept file is listed in its folder's `index.md`.
* **Links** — bundle-absolute and relative links resolve.
* **Acceptance IDs** — unique across the bundle; IDs not cited by any test are reported (warning).
* **Spec-first rule** (commit-msg hook) — if a commit touches `apps/` but not `specs/`, it is rejected unless the message contains `[no-spec]`.

Enable the hooks once per clone: `git config core.hooksPath .githooks`.

# Acceptance

- **SDD-01** — Given a commit that changes files under `apps/` and none under `specs/`, when the commit message lacks `[no-spec]`, then the commit-msg hook rejects it.
- **SDD-02** — Given any `.md` file under `specs/` other than `index.md`/`log.md`, when it lacks frontmatter or a non-empty `type`, then `spec_check.py` exits non-zero and names the file.
- **SDD-03** — Given two concepts declaring the same acceptance ID, when `spec_check.py` runs, then it fails and lists both locations.
- **SDD-04** — Given a concept file not listed in its folder `index.md`, when `spec_check.py` runs, then it fails with the missing entry.
