---
type: Component Spec
title: Personas
description: The tenant persona library - fields, how agents reference personas, snapshot resolution, per-call overrides and live switching while a call is running.
status: stable
tags: [architecture, personas]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-06T00:00:00Z" }
---

# Persona fields

| Field | Rules | Use |
|---|---|---|
| `name` | 1–40 chars | spoken name and prompt identity |
| `description` | ≤ 200 chars | shown in lists ("Warm, patient, ideal for claims") |
| `voice` | Deepgram Aura id, `aura-2-<name>-en` | text-to-speech voice |
| `speed` | 0.7–1.5, default 1.0 | speaking-rate multiplier |
| `greeting` | 1–300 chars | first words of an inbound call |
| `disclosure` | 1–300 chars | AI/recording disclosure, spoken after the greeting |
| `opening` | ≤ 400 chars, may be empty | first words of an outbound call; supports `{first_name}` and other call-context placeholders |
| `style` | ≤ 500 chars | free text speaking style injected in the system prompt |

# Library and references

* Personas belong to a tenant (table `personas`, [/data/data-model.md](/data/data-model.md)); CRUD at `/api/personas` ([/api/rest-api.md](/api/rest-api.md)).
* An agent's draft config holds `persona_id`. When `persona_id` is empty the inline `persona` object in the config is used (legacy and quick experiments).
* **Publish** resolves `persona_id` into the version snapshot (`persona` = the persona's fields plus `id`), so later edits to the library never change a published version.
* A persona referenced by an agent draft cannot be deleted (409 `persona_in_use`).

# Per-call override and live switching

* `POST /api/calls` accepts `persona_id`; the call's metadata stores it (`live.persona_id`) and the session uses that persona instead of the agent's.
* `PATCH /api/calls/{id}/live` with `persona_id` switches the persona of a running call (voice or text):
  1. the session's persona is replaced; the **next turn's** system prompt uses the new name and style;
  2. a `system` call event "Persona switched to <name>" is recorded and published;
  3. the greeting is **not** repeated;
  4. on a voice call, a TTS settings update with the new voice and speed is sent so the **next spoken sentence** uses it;
  5. the override is persisted in the call metadata so a restarted session keeps it.
* The effective persona for a call is: live override, else call-start override, else the version snapshot.

# Acceptance

- **PER-01** — Given the persona API, when a persona is created, updated and listed, then the fields round-trip and are scoped to the tenant; invalid `speed` or `voice` returns 422.
- **PER-02** — Given an agent whose draft has `persona_id`, when published, then the version snapshot contains the resolved persona, and editing the persona afterwards leaves that version unchanged.
- **PER-03** — Given `POST /api/calls` with `persona_id`, when the call starts, then the greeting uses that persona's greeting and name.
- **PER-04** — Given a running text call, when `PATCH /api/calls/{id}/live` sets a different `persona_id`, then the next model request's system prompt names the new persona, a "Persona switched to …" system event is stored, and no second greeting is produced.
- **PER-05** — Given a persona referenced by an agent draft, when deleted, then the API returns 409 `persona_in_use`; after unreferencing it, deletion succeeds.
- **PER-06** — Given a persona of another tenant, when referenced by an agent config or call, then the API rejects it (422 on publish/config, 404 on the call endpoints).
