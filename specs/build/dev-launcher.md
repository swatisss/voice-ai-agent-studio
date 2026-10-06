---
type: Tool Spec
title: Dev launcher
description: scripts/dev.py - starts the web frontend and the API together from one terminal with prefixed logs, pre-flight checks, readiness messages and clean shutdown.
status: stable
tags: [build, tooling, dx]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-06T00:00:00Z" }
---

# Usage

```bash
python scripts/dev.py                    # dev mode: web :3000 (hot reload) + API :8000 (auto-reload)
python scripts/dev.py --single-origin    # build the web export, serve everything from the API on :8000
python scripts/dev.py --fake             # no LLM keys: scripted fake LLM, hash embeddings, separate database
python scripts/dev.py --check            # pre-flight checks only
```

Windows without a `python` command: `py -3 scripts/dev.py`. Stdlib only (Python 3.9+).

| Flag | Meaning |
|---|---|
| `--single-origin` | Run `npm run build` (unless `--skip-build`), then only the API, which serves the static web app. No hot reload. Same shape as Cloud Run. |
| `--skip-build` | With `--single-origin`: reuse an existing `apps/web/out`. |
| `--api-port N`, `--web-port N` | Default 8000 and 3000. |
| `--no-reload` | Run the API without auto-reload. |
| `--fake` | `LLM_FAKE=1`, `EMBEDDINGS_PROVIDER=hash`, and `DATABASE_URL` defaulting to `apps/api/data/fake.db` so hash embeddings never mix with the real database. |
| `--install` | Run `scripts/setup.py --install` first (hooks, `.env`, `uv sync`, `npm ci`). |
| `--check` | Run the pre-flight checks, print the plan, exit. |

# Behavior

1. **Pre-flight** (before anything starts). Errors stop the launcher with exit code 1; warnings do not.
   * Errors: `uv` or `npm` not found; `apps/api/.venv` missing; `apps/web/node_modules` missing (when the web app is started or built); `apps/web/out` missing with `--skip-build`; a required port already in use. Every error names the fix (for example `python scripts/setup.py --install` or `--api-port`).
   * Warnings: `apps/api/.env` missing; no `GROQ_API_KEY` and no `OPENROUTER_API_KEY` (agent replies will fail; use `--fake`); only an OpenRouter key and no `LLM_ROLE_REALTIME` (see [runbook](/build/runbook-local.md)); no `DEEPGRAM_API_KEY` (Talk disabled, use Type).
   * Keys are read from the process environment and `apps/api/.env`; only whether each is set is printed, never a value.
2. **Dev mode services**
   * `api`: `uv run voiceai serve --port <api> --reload` in `apps/api`, with `CORS_ORIGINS` allowing `http://localhost:<web>` and `http://127.0.0.1:<web>`.
   * `web`: `npm run dev -- -p <web>` in `apps/web`, with `NEXT_PUBLIC_API_BASE=http://localhost:<api>` and telemetry off.
3. **Single-origin mode**: build step `npm run build` in `apps/web` with `NEXT_PUBLIC_API_BASE` empty (same origin), then one `api` service without reload.
4. **Output**: stdout and stderr of every process are merged, decoded as UTF-8, and printed line by line with a padded, colored tag (`[api]`, `[web]`, `[dev]` for the launcher). Child processes run unbuffered with UTF-8 so logs stream live on Windows consoles. Color is off when output is not a terminal or `NO_COLOR` is set.
5. **Readiness**: `/healthz` of the API and `/` of the web server are polled; each prints `<name> ready` once, then `READY - open <url>` when all are up. The first API start seeds the demo data and may take about a minute.
6. **Shutdown**: Ctrl+C, SIGTERM (and Ctrl+Break on Windows) stop every service's whole process tree (process group on POSIX, `taskkill /T` on Windows) and exit 0. If any service exits on its own, all others are stopped and the launcher exits with that service's exit code (1 if it was signalled).

# Acceptance

- **DEV-01** — Given dev mode with `--web-port 3100`, when the plan is built, then the API command carries `--reload` and the chosen API port, its `CORS_ORIGINS` includes `http://localhost:3100`, and the web service has `NEXT_PUBLIC_API_BASE=http://localhost:<api port>`.
- **DEV-02** — Given `--single-origin`, when the plan is built, then there is one build step with an empty `NEXT_PUBLIC_API_BASE` followed by a single non-reloading API service; with `--skip-build` the build step is absent.
- **DEV-03** — Given two services printing to stdout and stderr, when supervised, then every line appears once, prefixed with its service tag.
- **DEV-04** — Given one service exits with code 3 while another (which has spawned a grandchild) keeps running, then the launcher returns 3 and the whole other tree, grandchild included, is gone.
- **DEV-05** — Given a missing dependency directory, a missing tool, or a busy port, when pre-flight runs, then it reports an error naming the fix and `--check` exits 1; given everything present it exits 0.
- **DEV-06** — Given keys in `.env` and the environment, when pre-flight runs, then key warnings follow the rules above and no key value is ever printed; given `--fake`, the LLM warning is skipped and `DATABASE_URL` defaults to `fake.db` unless already set.
