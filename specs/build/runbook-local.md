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
* Keys: `OPENAI_API_KEY` (the LLM) and `DEEPGRAM_API_KEY` (voice). `OPENROUTER_API_KEY` is an optional fallback and model switch.

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
| OpenAI key, **no Deepgram** | Put `OPENAI_API_KEY` in `apps/api/.env`; use the **Type** tab on Test call | Everything except the microphone: resolve, escalate, console, insights, evaluation, dashboard |
| OpenRouter key only | Put `OPENROUTER_API_KEY` in `apps/api/.env`; no `LLM_ROLE_*` lines needed (OpenAI is skipped for lack of a key and the OpenRouter fallback answers) | Same as above |
| No LLM key | `LLM_FAKE=1 EMBEDDINGS_PROVIDER=hash` | UI and plumbing only: the agent answers with a canned placeholder, so the demo acts do not work |

The seeded Northgate agents run on the cascade pipeline and need `DEEPGRAM_API_KEY` for voice plus `OPENAI_API_KEY`. An agent switched to the realtime pipeline in its Voice tab needs only `OPENAI_API_KEY` for voice and no Deepgram key; try it from the Test call page first. Answering a real phone call locally (Twilio number, tunnel, `PUBLIC_BASE_URL`) or simulating one with no Twilio account is in [/build/runbook-phone.md](/build/runbook-phone.md); for a demo, `python scripts/phone_demo.py` does all of it from values in `.env` ([/build/phone-demo.md](/build/phone-demo.md)).

**Email, SMS and message calls** ([/architecture/contact-tools.md](/architecture/contact-tools.md)). With no settings every agent's messages go to the **outbox**: shown on the call detail, never delivered. To deliver for real:

* Email (Brevo, free plan 300 a day): create an account at brevo.com, verify a sender address (Senders & IP), create an API key (SMTP & API), then set `BREVO_API_KEY` and `EMAIL_FROM` (the verified sender; optional `EMAIL_FROM_NAME`).
* SMS and message calls (Twilio): with the account used for phone calls, buy or use a number that can send SMS and call, then set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and `TWILIO_FROM_NUMBER`. A trial account only reaches numbers verified under Phone Numbers > Verified Caller IDs.
* The seeded members' contacts are fictional; set `CONTACT_REDIRECT_EMAIL` and `CONTACT_REDIRECT_PHONE` to your own inbox and verified phone so every real message lands there.
* `/healthz` shows `messaging` with the provider of each channel; restart the API after changing `.env`.

Duplicate keys in `.env` are a trap: when a variable appears twice the later line wins, so a stale or truncated second `OPENAI_API_KEY=` silently replaces a good first one (OpenAI then answers 401 `invalid_api_key`).

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
* **Talk connects and drops at once, the call has no events** — the voice pipeline could not load. On Windows with Application Control the API log shows `DLL load failed while importing sentencex: An Application Control policy has blocked this file`. Ask IT to allow `apps/api/.venv`, or run the stack in Docker: `python scripts/docker_stack.py start`, then open `http://localhost:8080` ([/build/docker-stack.md](/build/docker-stack.md)). Stop `dev.py` first: both use `apps/api/data/voiceai.db`.
* **Dental tools return `connection_error`** — the dental demo mock is not running. `dev.py` and `docker_stack.py` start it on 8766 unless `--no-mock`; a `[dev]` warning says when the port is held by something else.
* **OpenAI 429 `insufficient_quota`** — the account has no credit or hit its rate limit. Add credit in the OpenAI console, or set `OPENROUTER_API_KEY` (the fallback then answers).
* **First knowledge search slow** — fastembed downloads its model once (~70 MB).
