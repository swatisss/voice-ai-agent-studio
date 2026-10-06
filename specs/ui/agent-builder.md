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
| Persona | name, voice (select of Aura-2 voices: thalia, andromeda, helena, apollo, arcas, orion), greeting, disclosure, style |
| Policy | editable lists (rules, escalate when, never), max turns, handoff and holding messages, safety screen toggle, voice filler toggle |
| Knowledge | Tenant docs with checkboxes (attached to this agent) + status badges; add via **Paste text**, **Upload** (.md/.txt/.pdf/.zip OKF), **From URL**; doc preview drawer showing chunks; **Test search** box showing scored results or "No answer" |
| Tools | Tenant tools with checkboxes; create/edit form: name, description, method, URL, parameters (JSON editor with validation), requires verification, is verification, timeout |
| Skills | Tenant skills with checkboxes; create/edit form: name, description, instructions (textarea), required tools (multi-select), escalate when |
| Versions | Table of versions (number, change note, source proposal link, date) |

Unsaved changes show a sticky bar "Unsaved changes — Save draft". Navigating away with unsaved changes asks for confirmation.

# Acceptance

- **UI-05** — Given an agent with a skill requiring a tool that is not attached, when Publish is clicked, then the modal shows the API error naming the missing tool and no version is created.
- **UI-06** — Given the Knowledge tab, when a `.zip` OKF bundle is uploaded, then each imported doc appears in the list with source "OKF".
- **UI-07** — Given the Knowledge tab, when "Test search" is run with an unrelated query, then the panel shows "No answer — the agent would offer a specialist".
