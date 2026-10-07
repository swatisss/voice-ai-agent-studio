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
# edit apps/api/.env and add the keys, then start the whole stack from this one terminal:
python scripts/dev.py                       # web http://localhost:3000 + API http://localhost:8000, logs prefixed [web] / [api]
```

Ctrl+C stops everything. `python scripts/dev.py --single-origin` builds the web export and serves it from the API on :8000 (what Cloud Run runs). Full reference: [/build/dev-launcher.md](/build/dev-launcher.md).

Manual alternative (two terminals):

```bash
cd apps/api && uv run voiceai serve         # terminal 1: http://localhost:8000 (auto-seeds an empty DB)
```

```bash
cd apps/web && npm run dev                  # terminal 2: http://localhost:3000; needs NEXT_PUBLIC_API_BASE=http://localhost:8000 in the environment
```

Or single-origin by hand: `npm run build` in `apps/web`, then `uv run voiceai serve` serves the exported site at http://localhost:8000.

# Running without some keys

| You have | Do this | What works |
|---|---|---|
| Groq key, **no Deepgram** | Put `GROQ_API_KEY` in `apps/api/.env`; use the **Type** tab on Test call | Everything except the microphone: resolve, escalate, console, insights, evaluation, dashboard |
| OpenRouter key only | Put `OPENROUTER_API_KEY` and the five `LLM_ROLE_*` lines (below) in `apps/api/.env` | Same as above |
| No LLM key | `LLM_FAKE=1 EMBEDDINGS_PROVIDER=hash` | UI and plumbing only: the agent answers with a canned placeholder, so the demo acts do not work |

OpenRouter-only role lines (the simulator's fallback is Groq-only, so all five are needed; the optional `turn` role falls back to a local heuristic when unavailable):

```
LLM_ROLE_REALTIME=openrouter:openai/gpt-oss-120b
LLM_ROLE_ANALYSIS=openrouter:openai/gpt-oss-120b
LLM_ROLE_DRAFTING=openrouter:openai/gpt-oss-120b
LLM_ROLE_SIMULATOR=openrouter:openai/gpt-oss-20b
LLM_ROLE_JUDGE=openrouter:openai/gpt-oss-120b
```

Without `DEEPGRAM_API_KEY` the Talk tab refuses the voice socket (close code 4500) and shows a toast; the API stays healthy. The refused voice call row stays `active` in the Calls list. Add the key later with no other change.

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
