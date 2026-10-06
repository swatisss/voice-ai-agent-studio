---
type: Change Proposal
title: CP-0004 One-command dev launcher
description: A single cross-platform script that starts the web frontend and the API from one terminal with prefixed live logs, pre-flight checks and clean shutdown.
status: stable
tags: [tooling, dx]
cp_state: implemented
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-06T00:00:00Z" }
---

# Why

Running the stack takes two terminals and different tools (`uv`/uvicorn for the API, `npm` for the Next.js dev server), plus the right environment wiring (`NEXT_PUBLIC_API_BASE`, CORS origins). New contributors and demo machines should start everything with one command and watch all logs in one place.

# What changes

`scripts/dev.py` starts the full stack from one terminal. Logs of every service are interleaved with a colored `[api]` / `[web]` prefix, readiness is announced, pre-flight checks catch missing tools, dependencies and busy ports before anything starts, and Ctrl+C stops the whole process tree. Two modes: **dev** (hot-reloading Next.js on :3000 plus the auto-reloading API on :8000) and **single-origin** (build the web export, serve everything from the API on :8000, as in production). A `--fake` flag runs without LLM keys against a separate database.

# Affected specs

* [/build/dev-launcher.md](/build/dev-launcher.md) — new: behavior and acceptance DEV-01…DEV-06.
* [/build/runbook-local.md](/build/runbook-local.md) — first run uses the launcher.
* [/process/conventions.md](/process/conventions.md) — new acceptance prefix `DEV`.

# Acceptance criteria

DEV-01…DEV-06 in [/build/dev-launcher.md](/build/dev-launcher.md).

# Tasks

1. Spec edits (done first).
2. `scripts/dev.py` — covers DEV-01…DEV-06.
3. `apps/api/tests/test_dev_launcher.py`.
4. README, `AGENTS.md`, runbook updates.

# Risks and rollout

* `next dev` and `uv run` start-up behavior differs by OS; process-tree shutdown uses `taskkill /T` on Windows and process groups elsewhere. Verified on Windows here; macOS/Linux paths are exercised only by the unit tests.

# Out of scope

Process supervision in production (Cloud Run runs one container), Docker Compose, auto-opening the browser.
