---
type: Change Proposal
title: CP-0003 Honor LLM role overrides from apps/api/.env
description: LLM_ROLE_<ROLE> overrides are only read from real environment variables; the documented .env file is ignored, so OpenRouter-only setups silently keep calling Groq.
status: stable
cp_state: implemented
tags: [llm, config, bugfix]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-06T00:00:00Z" }
---

# Why

[/architecture/llm-gateway.md](/architecture/llm-gateway.md) says `LLM_ROLE_<ROLE>` overrides a role at deploy time, and `apps/api/.env.example` lists them under optional overrides. The gateway read them only from `os.environ`; settings loaded from `.env` are never exported to the process environment, so a developer who put `LLM_ROLE_REALTIME=openrouter:...` in `.env` (the natural place when running without a Groq key) got no effect. Found while documenting how to run locally without a speech key.

# What changes

`LLM_ROLE_REALTIME`, `_ANALYSIS`, `_DRAFTING`, `_SIMULATOR` and `_JUDGE` are honored from either a real environment variable (which wins) or a line in `apps/api/.env`.

# Affected specs

* [/architecture/llm-gateway.md](/architecture/llm-gateway.md) — configuration note and LG-06.
* [/build/runbook-local.md](/build/runbook-local.md) — a "run without Deepgram / without Groq" section.

# Acceptance criteria

LG-06 (extended) and LG-07 in the gateway spec.

# Tasks

1. Spec edits (done first).
2. `Settings` gains the five fields; `Gateway` falls back to them — covers LG-06, LG-07.
3. Gateway tests.

# Out of scope

Ending the call row when a voice socket is refused for a missing speech key (it stays `active`; see the runbook note).
