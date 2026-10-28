---
type: UI Spec
title: Member memory
description: What an agent remembers about one member - a timeline of active and retired memories with their source, restore, erase and export.
status: stable
tags: [ui, memory]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-28T00:00:00Z" }
---

# Page (`/members/memory/?ref=…&agent=…`)

Reached from a call's detail page (**Member memory** link next to the verified member, [/ui/calls.md](/ui/calls.md)). Header: the member reference masked to its last three digits (`EVG-•••913`) and first name, an **agent** select (agents of the tenant that hold memory for this member), and the buttons **Export** and **Erase member** (v1 has no roles, so anyone working in the tenant sees them; [/product/scope.md](/product/scope.md)).

Body, for the selected agent ([/architecture/agent-memory.md](/architecture/agent-memory.md)):

| Section | Content |
|---|---|
| Facts | Active facts, newest confirmed first: text, category chip, "learned on {date}", **Why the agent knows this** (link to the source call's transcript at that turn), "expires {date}" |
| Episodes | One card per call summary, newest first, linked to its call |
| Retired | Retired facts, struck through, with "replaced by …" (or "expired") and the agent's reason from the update event; **Restore** |
| History | The memory events in time order: added, superseded, confirmed, restored, expired, erased; who did it (the agent, a person in the Studio, the system) |

**Erase member** opens a confirmation ("Erase everything every agent remembers about this member? This cannot be undone.") and then shows the empty state "Nothing remembered about this member." with the erasure record in History. **Export** downloads the JSON from the API. No memory text can be edited.

# Acceptance

- **UI-44** — Given a member with active, retired and expired-then-purged memories on the Customer Care agent, when the page opens, then facts, episodes and retired items are shown as above, each fact's source link opens the call transcript at the right turn, retired items show what replaced them and why, and the member reference is masked.
- **UI-45** — Given the member memory page, when Erase member is confirmed, then the page shows the empty state and an erasure entry without content, and selecting any other agent shows the same empty state; when it is cancelled, nothing changes.
