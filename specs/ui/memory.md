---
type: UI Spec
title: Caller memory
description: The Memory page - callers with a profile, their remembered facts with provenance, pending notes, the diff of every dream run, and edit and delete controls.
status: draft
tags: [ui, memory]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-16T00:00:00Z" }
---

# List (`/memory/`)

A table of callers who have a profile or pending notes (`GET /api/memory/members`): member (masked, for example `EVG-•••913`), facts, waiting notes ("3 of 10"), profile version, last dream. Search by member reference. Empty state: "No caller memory yet. Turn on memory in an agent's Memory tab, then finish a call with a verified caller." Row click → detail.

# Detail (`/memory/detail/?member=…`)

Header: masked member, profile version, **Dream now** button (disabled with the hint "No new notes" when none are waiting), **Delete all memory** (danger, confirmation: "This deletes every note, profile version and dream run for this caller. This cannot be undone.").

* **Profile** card: facts grouped by kind. Each fact shows its text, a badge for sensitivity (Low · Normal · High), a *Stated* or *Inferred* badge, "confirmed <date>", an expiry when set, and links to the source calls. Row actions: **Edit** (inline text, ≤ 200 chars) and **Remove**. A footer shows the retention period and the cap ("17 of 25 facts").
* **Waiting notes** card: each pending note with date, call link and summary; header "These feed the next dream (3 of 10)."
* **Dream history** card: newest first, each run with date, trigger (Threshold · Manual), status, notes used and a **diff**: added facts with a plus sign, updated facts as before → after, confirmed facts counted, retired facts struck through with the reason, contradictions flagged. Failed runs show the error.
* **Previous versions**: a version select shows any earlier profile read-only.

New runs and edits update the page through the `memory` events without reload.

# Acceptance

- **UI-38** — Given a member with a profile and waiting notes, when the Memory page and the detail open, then the list shows facts, waiting count and version, and the detail shows each fact with its sensitivity, stated/inferred badge and source call, and the waiting notes.
- **UI-39** — Given a dream run that added, updated, confirmed and retired facts, then the Dream history card shows each change with its reason, and a version select displays an earlier version read-only.
- **UI-40** — Given a fact, when Edit is saved or Remove is confirmed, then the profile shows the change and a new version; and "Delete all memory" empties the caller's detail after its confirmation, and the caller leaves the list.
