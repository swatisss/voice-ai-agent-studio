---
type: UI Spec
title: Settings
description: Business-unit settings page - allow the realtime voice pipeline and manage the unit's own OpenAI key.
status: stable
tags: [ui, settings, tenancy]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-27T00:00:00Z" }
---

# Settings (`/settings/`)

One page for the selected business unit (tenant), reached from the **Settings** navigation item ([/ui/app-shell.md](/ui/app-shell.md)). Behavior: [/architecture/tenant-settings.md](/architecture/tenant-settings.md). Data: `GET /api/tenant-settings`.

| Card | Content |
|---|---|
| **Voice pipelines** | *Cascade* shown as always on. Toggle **Allow realtime speech-to-speech** with the note "One OpenAI model listens and speaks: lower delay, higher cost per minute, less control over exact wording." Saving sends `PUT /api/tenant-settings`. A 409 `pipeline_in_use` shows the message "Switch these agents to Cascade and publish them first:" followed by the agent names, and the toggle returns to on. |
| **OpenAI key** | Status line: "Using the platform key" (no key, fallback on), "No key - realtime calls are unavailable" (no key, fallback off), or "Own key ending in ••••<last4>, saved <relative time>". A password input (never pre-filled), **Save key** (`PUT /api/tenant-settings/openai-key`) and, when a key is set, **Remove key** (`DELETE`). Toggle **Use the platform key when this unit has none** (`openai_platform_fallback`). Note: "Used only for realtime speech-to-speech calls. The key is stored encrypted and cannot be shown again." A 503 `secrets_unavailable` shows "Key storage is not configured on this server (TENANT_SECRETS_KEY)." |

After a successful save the input is cleared. Switching business unit reloads the page's data (UI-01).

# Acceptance

- **UI-40** — Given the Settings page of a unit that allows only Cascade, when *Allow realtime speech-to-speech* is turned on and a key `sk-test…wxyz` is saved, then the page shows "Own key ending in ••••wxyz", the input is empty, a reload shows the same state without the key text anywhere in the page, and the agent builder's Realtime card is enabled for that unit; turning the toggle off while a realtime agent exists shows the agent's name and leaves the toggle on.
