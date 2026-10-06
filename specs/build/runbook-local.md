---
type: Runbook
title: Local runbook
description: Install prerequisites, configure keys, run the API and web app, seed data and run checks on a developer machine (Windows, macOS, Linux).
status: stable
tags: [build, runbook, local]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Prerequisites

* Python 3.12 and **uv** — Windows: `winget install --source winget Python.Python.3.12 astral-sh.uv`; macOS: `brew install python@3.12 uv`.
* Node.js LTS (24.x) — Windows: `winget install --source winget OpenJS.NodeJS.LTS`; macOS: `brew install node`.
* Windows note: if `winget install astral-sh.uv` stalls on an admin prompt, `py -3.12 -m pip install --user uv` and run uv as `py -m uv`.
* Keys: `GROQ_API_KEY` (required for the agent), `DEEPGRAM_API_KEY` (voice), `OPENROUTER_API_KEY` (optional fallback / model switching).

# First run

```bash
python scripts/setup.py --install           # hooks, apps/api/.env, uv sync, npm ci (use `py -3` on Windows)
# edit apps/api/.env and add the keys, then:
cd apps/api
uv run voiceai seed --reset                 # optional: the server auto-seeds an empty DB
uv run voiceai serve                        # http://localhost:8000
```

In a second terminal:

```bash
cd apps/web
npm install
npm run dev                                 # http://localhost:3000 (talks to :8000)
```

Single-origin mode (what Cloud Run runs): `npm run build` in `apps/web`, then `uv run voiceai serve` serves the exported site at http://localhost:8000.

# Checks

```bash
python scripts/spec_check.py               # from repo root
cd apps/api && uv run pytest
cd apps/web && npm run build
```

# Useful commands

| Command | Purpose |
|---|---|
| `uv run voiceai seed --reset` | Drop and recreate the DB with demo data |
| `uv run voiceai reindex` | Re-embed all knowledge chunks (after changing embedder) |
| `uv run voiceai chat --agent <id>` | Talk to an agent in the terminal (text channel) |
| `LLM_FAKE=1 uv run pytest` | Tests use the fake LLM (default in tests) |

# Troubleshooting

* **Mic blocked** — use `http://localhost` (not an IP) or HTTPS.
* **Echo / agent interrupts itself** — use a headset.
* **Voice closes with 4500** — `DEEPGRAM_API_KEY` missing; use Type mode.
* **Groq 429** — free-tier limit; enable billing or set `LLM_ROLE_REALTIME=openrouter:openai/gpt-oss-120b`.
* **First knowledge search slow** — fastembed downloads its model once (~70 MB).
