---
type: Decision Record
title: Tech stack
description: Languages, frameworks, providers and the version policy for the platform; the single reference for dependencies.
status: stable
tags: [architecture, stack, dependencies]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Backend — `apps/api` (Python package `voiceai`)

| Concern | Choice |
|---|---|
| Runtime | Python 3.12, managed with **uv** (`uv sync`, `uv run`) |
| Web framework | FastAPI + Uvicorn |
| ORM / DB | SQLAlchemy 2.x async; `aiosqlite` locally, `asyncpg` for Postgres |
| Settings | `pydantic-settings` (env vars, `.env`) |
| LLM client | `openai` Python SDK (OpenAI-compatible endpoints of Groq and OpenRouter) |
| HTTP client | `httpx` (also used in-process via ASGI transport for relative tool URLs) |
| Embeddings | `fastembed` with `BAAI/bge-small-en-v1.5` (384-d, local CPU); deterministic `hash` embedder for tests |
| Vector search | NumPy cosine similarity in-process ([/decisions/adr-0004-storage-and-vectors.md](/decisions/adr-0004-storage-and-vectors.md)) |
| Voice | `pipecat-ai` with extras `deepgram`, `silero`, `websocket` |
| Docs parsing | `pypdf` for PDFs; stdlib `html.parser` for URLs; `pyyaml` for frontmatter |
| Tests | `pytest`, `pytest-asyncio`, fake LLM provider |

# Web — `apps/web`

| Concern | Choice |
|---|---|
| Runtime | Node.js LTS (24.x at time of writing), npm |
| Framework | Next.js (App Router) with `output: "export"` — static files served by the API service |
| UI | React 19, Tailwind CSS 4, hand-written small components (no component CLI), `lucide-react` icons |
| Charts | `recharts` |
| Voice client | Hand-written: `getUserMedia` + AudioWorklet (16 kHz PCM16 out) + WebAudio playback (24 kHz PCM16 in) |
| Data fetching | `fetch` wrappers + `EventSource` for SSE; no state library |

# Providers

| Purpose | Default | Alternatives (config only) |
|---|---|---|
| LLM — all roles | Groq `openai/gpt-oss-120b` | Any OpenRouter model; Groq `openai/gpt-oss-20b` |
| Speech-to-text | Deepgram `nova-3` streaming | — |
| Text-to-speech | Deepgram `aura-2-thalia-en` (per persona voice) | Other Deepgram Aura-2 voices |

Model IDs MUST be confirmed against the provider console during the spike ([/verification/spikes.md](/verification/spikes.md)); they live only in `apps/api/config/models.yaml`, never in code.

# Version policy

* Lock files (`uv.lock`, `package-lock.json`) are committed; installs are reproducible.
* Upgrades are `[no-spec]` commits unless they change behavior.
* Pipecat moves fast: its usage is confined to `voiceai/voice/` and verified by `tests/test_voice_smoke.py`.
