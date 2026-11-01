---
type: UI Spec
title: Settings
description: Business-unit settings page - voice pipelines, the unit's own OpenAI key, the front desk of routed conversations, API keys and webhooks.
status: draft
tags: [ui, settings, tenancy]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-27T00:00:00Z" }
---

# Settings (`/settings/`)

One page for the selected business unit (tenant), reached from the **Settings** navigation item ([/ui/app-shell.md](/ui/app-shell.md)). Behavior: [/architecture/tenant-settings.md](/architecture/tenant-settings.md). Data: `GET /api/tenant-settings`.

| Card | Content |
|---|---|
| **Voice pipelines** | *Cascade* shown as always on. Toggle **Allow realtime speech-to-speech** with the note "One OpenAI model listens and speaks: lower delay, higher cost per minute, less control over exact wording." Saving sends `PUT /api/tenant-settings`. A 409 `pipeline_in_use` shows the message "Switch these agents to Cascade and publish them first:" followed by the agent names, and the toggle returns to on. |
| **OpenAI key** | Status line: "Using the platform key" (no key, fallback on), "No key - realtime calls are unavailable" (no key, fallback off), or "Own key ending in ••••<last4>, saved <relative time>". A password input (never pre-filled), **Save key** (`PUT /api/tenant-settings/openai-key`) and, when a key is set, **Remove key** (`DELETE`). Toggle **Use the platform key when this unit has none** (`openai_platform_fallback`). Note: "Used only for realtime speech-to-speech calls. The key is stored encrypted and cannot be shown again." A 503 `secrets_unavailable` shows "Key storage is not configured on this server (TENANT_SECRETS_KEY)." |
| **Front desk** | How routed conversations open ([/architecture/supervisor-routing.md](/architecture/supervisor-routing.md)): **Persona** select (library personas), **Voice pipeline** (Cascade, or Realtime when allowed), **Default agent for members** and **for staff** (routable agents of that scope, or "None"), **Ask a clarifying question** (*Never*, *Once*, *Up to twice*), **Confidence needed** (slider 0.3–0.95 with "Use the model's default" checkbox), **Connecting message**, **Routing suite pass mark** (%), **Routing** (*Embedding* (default) or *Decision model*; the second shows "Not configured on this server" when no decision model is set up, and "Blocked by PHI mode" when it is hosted and PHI mode is on), **Stage A clear win** and **Stage A margin** (sliders, with "Higher: more requests go to the decision model"). A line under the title shows the decision model's status from `/healthz` ("Decision model: configured", "not configured" or "blocked by PHI mode"). Saves with `PUT /api/tenant-settings/front-desk`; API errors show next to the field. |
| **API keys** | Table: name, prefix (`vak_ab12cd34…`), scope (*Members* / *Staff*), limits, created, last used, **Revoke** (confirmation dialog in the app). **New key** opens a form (name, scope, requests per minute, concurrent voice calls); after create the full key is shown once in a copy box with the warning "Copy this key now. It will not be shown again." and is gone after the dialog closes ([/api/public-api.md](/api/public-api.md)). |
| **Webhooks** | Endpoints with URL, events (checkboxes), *Include transcripts* (off; note "Transcripts contain member information"), enabled switch, **Rotate secret**, **Delete**; the secret is shown once after create or rotate. Each endpoint expands to its last 50 deliveries (event, status, attempts, response code, time) with **Resend** ([/architecture/webhooks.md](/architecture/webhooks.md)). |

After a successful save the input is cleared. Switching business unit reloads the page's data (UI-01).

# Acceptance

- **UI-40** — Given the Settings page of a unit that allows only Cascade, when *Allow realtime speech-to-speech* is turned on and a key `sk-test…wxyz` is saved, then the page shows "Own key ending in ••••wxyz", the input is empty, a reload shows the same state without the key text anywhere in the page, and the agent builder's Realtime card is enabled for that unit; turning the toggle off while a realtime agent exists shows the agent's name and leaves the toggle on.
- **UI-56** — Given Settings → API keys, when a member key is created, then the full key is shown once with a copy button and the warning; after closing, the table shows only its prefix and scope; **Revoke** asks for confirmation, marks it revoked and a request with that key then fails with 401.
- **UI-57** — Given Settings → Webhooks, when an endpoint is added for `conversation.ended`, then its secret is shown once; after an API conversation ends, the endpoint's deliveries list the event with its status; **Resend** on a failed delivery adds an attempt.
- **UI-58** — Given Settings → Front desk, when the persona, the member default agent and *Ask a clarifying question: Once* are saved, then a reload shows the same values, a full-flow test call greets with that persona, and choosing an internal agent as the member default is not offered.
- **UI-64** — Given Settings → Front desk, when *Decision model* and a clear win of 0.70 are saved, then a reload shows them and the next full-flow call's routing trace shows the mode; on a server without a decision model the option shows "Not configured on this server" and routing uses the embedding.
