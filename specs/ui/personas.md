---
type: UI Spec
title: Personas page
description: Create, edit and delete the tenant's personas (name, voice, speed, greeting, disclosure, outbound opening, speaking style) and try one in a test call.
status: stable
tags: [ui, personas]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-06T00:00:00Z" }
---

# Layout (`/personas/`)

* Header with **New persona**.
* Card grid, one card per persona: name, description, voice and speed chips, the greeting in quotes, the agents using it (by name), and actions **Edit**, **Try in test call** (opens `/test-call/?persona=<id>`), **Delete**.
* **Editor modal** fields: name, description, voice (select of the six Aura-2 voices with a short descriptor, e.g. "Thalia — warm, female"), speed (slider 0.7–1.5 with the current value), greeting, disclosure, outbound opening (hint: "Placeholders: {first_name}"), speaking style. Save validates through the API and shows field errors inline.
* Deleting a persona in use shows the API message ("Used by: …") and does not delete.
* Empty state: "No personas yet — create the voice of your first agent."

# Acceptance

- **UI-21** — Given the Personas page, when a persona is created, edited and deleted, then each change appears without reload; deleting a persona used by an agent is refused with the agents listed.
