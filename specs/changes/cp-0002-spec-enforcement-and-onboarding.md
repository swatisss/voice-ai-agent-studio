---
type: Change Proposal
title: CP-0002 Spec enforcement in CI and contributor onboarding
description: Make "specs are always up to date" enforceable on any machine - CI gate, PR-level spec-first/log/lifecycle rules, an acceptance-coverage ratchet, a cross-platform setup script, and a README that teaches the workflow.
status: stable
cp_state: implemented
tags: [process, sdd, ci]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-06T00:00:00Z" }
---

# Why

The v1 guardrails are local git hooks. Hooks only protect a clone that enabled them, run only on machines that have Python, and can be skipped with `--no-verify`. New contributors (and coding agents on other machines) had no single place that explained how to start spec-first, how to generate code from specs, or how drift is prevented.

# What changes

1. **CI is the real gate.** A GitHub Actions workflow runs the spec checks, backend tests and the web build on every pull request and on pushes to `main`. Branch protection (a GitHub setting, documented not automated) makes it required.
2. **PR-level rules** in `scripts/spec_check.py --ci --base <ref>`:
   * spec-first over the whole PR (not just the last commit), with `[no-spec]` in any commit message or the `no-spec` PR label as the exemption;
   * spec edits must come with a `specs/log.md` entry;
   * code may not ship against a `status: draft` spec or a `cp_state: proposed` change proposal that the same PR touches;
   * tests may only cite acceptance IDs that exist in the specs;
   * **ratchet:** every acceptance ID in a `status: stable` spec must be cited by a test or be listed in `scripts/acceptance-baseline.txt` (the known manual-verification gap). New uncovered IDs fail; covered IDs must leave the baseline.
3. **Test-only and lock-file changes** under `apps/` no longer need a spec change (they do not change behavior).
4. **`scripts/setup.py`** bootstraps any clone on Windows, macOS or Linux: enables the hooks, creates `apps/api/.env`, optionally installs dependencies, runs the spec check.
5. **README** documents onboarding, spec-first development, regenerating code from specs on another machine, and the enforcement layers.
6. A PR template reminds authors of the checklist.

# Affected specs

* [/process/sdd-workflow.md](/process/sdd-workflow.md) — guardrails rewritten as three layers; new rules; SDD-01 refined; SDD-05…09 added.
* [/build/runbook-local.md](/build/runbook-local.md) — first run uses `scripts/setup.py`.

# Acceptance criteria

SDD-01 (refined), SDD-05, SDD-06, SDD-07, SDD-08, SDD-09 in [/process/sdd-workflow.md](/process/sdd-workflow.md).

# Tasks

1. Spec edits (this CP, done first).
2. `scripts/spec_check.py`: `--ci`, `--base`, `--baseline`; behavior-path exclusions; ratchet — covers SDD-01, SDD-05…08.
3. `scripts/acceptance-baseline.txt` with the current manual-verification gap.
4. `scripts/setup.py` — covers SDD-09.
5. `.github/workflows/ci.yml`, `.github/pull_request_template.md`.
6. Tests in `apps/api/tests/test_spec_check.py` and `test_setup_script.py`.
7. README rewrite; `AGENTS.md` pointer.

# Risks and rollout

* The workflow cannot be exercised locally; the first push to GitHub is its first real run. Action versions are pinned to majors that exist today and should be bumped by Dependabot.
* The baseline is a debt list: UI-*, VO-01, VO-03 and DEP-03 are verified by hand. Adding automated browser/voice tests is a separate CP.

# Out of scope

* Automating GitHub branch protection or CODEOWNERS (needs repository admin rights and the user's GitHub handle).
* Semantic drift detection (does the code do what prose says) — covered by acceptance-ID tests and review, see the README.
