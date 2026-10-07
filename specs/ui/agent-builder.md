---
type: UI Spec
title: Agent builder
description: Agents list and the builder tabs - overview, persona, policy, knowledge, tools, skills, versions - with save, publish and test actions.
status: stable
tags: [ui, builder]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Agents list (`/agents/`)

Cards: name, description, published version (or "Not published"), updated time; actions **Open**, **Test**. Button **New agent** (modal: name, description) creates an agent with default persona/policy and opens it.

# Builder (`/agents/edit/?id=…`)

Header: agent name, version badge (`v3` / "Draft changes" when draft differs from published), buttons **Save draft**, **Publish** (modal with change note; shows validation errors from the API), **Test call** (opens `/test-call/?agent=…`).

Tabs:

| Tab | Content |
|---|---|
| Overview | Name, description, realtime model select (`GET /api/models`, "Default (role setting)" first), counts of docs/tools/skills |
| Persona | Choose a **library persona** (select, with a read-only summary and a link to the Personas page). Agents without a library persona edit the inline persona fields (name, voice, speed, greeting, disclosure, outbound opening, style) as before. |
| Policy | editable lists (rules, escalate when, never), max turns, handoff and holding messages, safety screen toggle, voice filler toggle |
| Voice | **Turn detection**: two selectable cards, *Normal detection* ("ends the turn after a silence") and *Semantic detection* ("also understands whether the caller has finished"); sliders for silence threshold (200–2000 ms) and, in semantic mode, extra wait (0–4000 ms); evaluator choice (*Local rules* / *LLM check*, with a note that it adds a small model call); *Allow the caller to interrupt* toggle. Values save with the draft and are versioned on publish. |
| Knowledge | Tenant docs with checkboxes (attached to this agent) + status badges; add via **Paste text**, **Upload** (.md/.txt/.pdf/.zip OKF), **From URL**; doc preview drawer showing chunks; **Test search** box showing scored results or "No answer" |
| Tools | Tenant tools with checkboxes; create/edit form: name, description, method, URL, parameters (JSON editor with validation), requires verification, is verification, timeout |
| Skills | Tenant skills with checkboxes; create/edit form: name, description, instructions (textarea), required tools (multi-select), escalate when |
| Versions | Table of versions (number, change note, source proposal link, date) |

Unsaved changes show a sticky bar "Unsaved changes — Save draft". Navigating away with unsaved changes asks for confirmation.

# Acceptance

- **UI-05** — Given an agent with a skill requiring a tool that is not attached, when Publish is clicked, then the modal shows the API error naming the missing tool and no version is created.
- **UI-06** — Given the Knowledge tab, when a `.zip` OKF bundle is uploaded, then each imported doc appears in the list with source "OKF".
- **UI-22** — Given the Voice tab, when *Semantic detection* is selected, then the extra-wait and evaluator controls appear (hidden in *Normal detection*), and after Save draft and Publish the new version's snapshot contains the chosen values.
- **UI-07** — Given the Knowledge tab, when "Test search" is run with an unrelated query, then the panel shows "No answer — the agent would offer a specialist".
