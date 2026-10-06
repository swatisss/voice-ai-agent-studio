---
type: Component Spec
title: Deployment
description: Local zero-infrastructure development and the GCP Cloud Run deployment topology, configuration and constraints.
status: stable
tags: [architecture, deployment, gcp]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Local

* API: `uv run voiceai serve` on `http://localhost:8000` with `DATABASE_URL=sqlite+aiosqlite:///./data/voiceai.db` (default).
* Web dev server: `npm run dev` on `http://localhost:3000`, calling the API at `NEXT_PUBLIC_API_BASE=http://localhost:8000` (CORS allows `localhost:3000`).
* Web production build: `npm run build` exports static files to `apps/web/out/`; the API serves them at `/` when `WEB_DIST_DIR` points there (default `../web/out` relative to `apps/api`).
* Mic access works on `localhost` without HTTPS.
* Seeding: `uv run voiceai seed --reset`. The app also seeds automatically on first start when the DB is empty (`AUTO_SEED=1`, default).

# GCP (Cloud Run)

One container image (multi-stage `infra/Dockerfile`): stage 1 builds the web export with Node 22; stage 2 is Python 3.12 slim with uv, the `voiceai` package, the web `out/` folder, and the fastembed model pre-downloaded at build time.

| Setting | Value | Why |
|---|---|---|
| Service | `voiceai` | single service: API + web + voice + jobs |
| Region | close to the demo audience (default `us-central1`) | latency to Groq/Deepgram US endpoints |
| `--min-instances` / `--max-instances` | 1 / 1 | in-process event bus and job worker ([/decisions/adr-0005-single-service.md](/decisions/adr-0005-single-service.md)) |
| `--no-cpu-throttling` | on | background jobs run outside requests |
| `--timeout` | 3600 | long WebSocket voice calls and SSE |
| `--session-affinity` | on | sticky WebSockets |
| CPU / memory | 2 vCPU / 2 GiB | VAD + embeddings |
| Secrets | Secret Manager → env `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `DEEPGRAM_API_KEY` | |

Database options:

* **A — Ephemeral (fastest):** default SQLite inside the container; auto-seeded on start; data resets on redeploy/restart. Good for a demo URL.
* **B — Persistent:** Cloud SQL for PostgreSQL 16, `DATABASE_URL=postgresql+asyncpg://USER:PASS@/voiceai?host=/cloudsql/PROJECT:REGION:INSTANCE` with the Cloud SQL connection attached (`--add-cloudsql-instances`).

Deploy script: `infra/deploy-cloudrun.sh` ([/build/runbook-gcp.md](/build/runbook-gcp.md)).

# Health

`GET /healthz` → `{"status":"ok","db":true,"jobs":true,"providers":{"groq":bool,"openrouter":bool,"deepgram":bool}}` (provider booleans = key configured, no network call).

# Acceptance

- **DEP-01** — Given a fresh checkout with only `GROQ_API_KEY` set, when `voiceai serve` starts, then the DB is created and seeded and `/healthz` reports `status: ok`.
- **DEP-02** — Given `WEB_DIST_DIR` with an exported build, when `/` and `/agents/` are requested, then the static pages are served and unknown `/api/*` paths still return JSON 404.
- **DEP-03** — Given the Dockerfile, when built, then the image contains the web export and the fastembed model so first requests need no downloads.
