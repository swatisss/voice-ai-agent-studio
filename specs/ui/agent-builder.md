---
type: UI Spec
title: Agent builder
description: Agents list and the builder tabs - overview, persona, policy, knowledge, tools, skills, versions - with save, publish and test actions.
status: draft
tags: [ui, builder]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Agents list (`/agents/`)

Cards: name, description, **mode badge** (Inbound / Outbound / Internal), published version (or "Not published"), updated time; actions **Open**, **Test**. Button **New agent** (modal: name, description) creates an agent with default persona/policy and opens it.

# Builder (`/agents/edit/?id=…`)

Header: agent name, version badge (`v3` / "Draft changes" when draft differs from published), buttons **Save draft**, **Publish** (modal with change note; shows validation errors from the API), **Run tests** (saves the draft if it has unsaved changes, then starts a test-suite run on the draft, [/architecture/test-suites.md](/architecture/test-suites.md); shows progress "Testing 7 of 18" and then "5 of 6 scenarios passed every run" linking to the run; never blocks Publish; disabled with a note when the agent has no scenarios), **Test call** (opens `/test-call/?agent=…`).

Tabs:

| Tab | Content |
|---|---|
| Overview | Name, description, realtime model select (`GET /api/models`, "Default (role setting)" first), counts of docs/tools/skills; **mode** select (Inbound / Outbound / Internal) and, for outbound agents, the **targets URL** |
| Persona | Choose a **library persona** (select, with a read-only summary and a link to the Personas page). Agents without a library persona edit the inline persona fields (name, voice, speed, greeting, disclosure, outbound opening, style) as before. |
| Policy | editable lists (rules, escalate when, never), max turns, handoff and holding messages, safety screen toggle, voice filler toggle |
| Voice | **Voice pipeline**: two selectable cards, *Cascade* ("speech-to-text, the agent brain, text-to-speech; the default") and *Realtime speech-to-speech* ("one OpenAI model listens and speaks; lower delay, higher cost"; disabled with the note "Not enabled for this business unit - turn it on in Settings" and a link to `/settings/` when the tenant's `allowed_pipelines` lacks `realtime`); with Realtime, a **Realtime voice** select (voices from `GET /api/models`) replaces the persona voice, and the evaluator and extra-wait controls below are disabled with a note "The realtime service decides when the caller has finished". **Transfer to** (phone number in international format or `sip:` URI, optional): where a live phone call is redirected after a hand-off. **Turn detection**: two selectable cards, *Normal detection* ("ends the turn after a silence") and *Semantic detection* ("also understands whether the caller has finished"); sliders for silence threshold (200–2000 ms) and, in semantic mode, extra wait (0–4000 ms); evaluator choice (*Local rules* / *LLM check*, with a note that it adds a small model call); *Allow the caller to interrupt* toggle. Values save with the draft and are versioned on publish. |
| Knowledge | Tenant docs with checkboxes (attached to this agent) + status badges; add via **Paste text**, **Upload** (.md/.txt/.pdf/.zip OKF), **From URL**; doc preview drawer showing chunks; **Test search** box showing scored results or "No answer" |
| Tools | Tenant tools with checkboxes; create/edit form: name, description, method, URL, parameters (JSON editor with validation), requires verification, is verification, timeout |
| Skills | Tenant skills with checkboxes; create/edit form: name, description, instructions (textarea), required tools (multi-select), escalate when |
| Memory | **Remember callers between calls** toggle (on by default); **Remember things like…** and **Never remember…** text boxes, pre-filled with the defaults and a note "Health details, payment details and ID numbers are never remembered, whatever you write here"; **Forget call summaries after** (days) and **Forget facts after** (days); **Trust verified caller ID (demo only)** toggle with a note that it skips the date of birth only for read-only lookups on US calls with full carrier attestation ([/architecture/agent-memory.md](/architecture/agent-memory.md), [/architecture/caller-verification.md](/architecture/caller-verification.md)) |
| Evaluation | **Checks this agent is scored on** (`GET /api/agents/{id}/checks` for the draft): grouped list with *Built-in*, *From your policy* or *Custom* tags and a *Hard gate* badge, refreshed after Save draft, so a new Never rule visibly becomes a check; **Custom checks** editor (question, group, hard gate; up to ten); **Judge share of calls** (0–100 %, note: "Escalated, thumbs-down and hard-failed calls are always judged"); **Slow-response limit** (p95, ms); **Run tests when publishing** switch (`evaluation.test_on_publish`); links **Test scenarios** (`/evaluation/?agent=…&view=tests`) and **See scores** to `/evaluation/?agent=…` ([/architecture/call-scoring.md](/architecture/call-scoring.md)) |
| Versions | Table of versions (number, change note, source proposal link, date) |

Unsaved changes show a sticky bar "Unsaved changes — Save draft". Navigating away with unsaved changes asks for confirmation.

# Acceptance

- **UI-42** — Given the Memory tab of a draft agent, when memory is switched off, the retention is set to 30 and 180 days and Publish is clicked, then the new version's snapshot holds those values; a retention outside the allowed range shows the API's validation error; a new agent shows the toggle on and the default texts.
- **UI-49** — Given the Evaluation tab of a draft agent, when a Never item is added on the Policy tab and the draft is saved, then the Evaluation tab lists a new hard-gate check *From your policy* with that text; adding a custom check and publishing puts it in the new version's snapshot; an eleventh custom check shows the API's validation error.
- **UI-53** — Given a draft with unsaved changes, when **Run tests** is clicked, then the draft is saved, a run on the draft starts, the header shows its progress and then the pass^k result linking to the run, and **Publish** stays enabled throughout.
- **UI-05** — Given an agent with a skill requiring a tool that is not attached, when Publish is clicked, then the modal shows the API error naming the missing tool and no version is created.
- **UI-06** — Given the Knowledge tab, when a `.zip` OKF bundle is uploaded, then each imported doc appears in the list with source "OKF".
- **UI-26** — Given the Agents list and an agent's Overview tab, then each agent shows its mode, and changing the mode and targets URL saves with the draft and is part of the published version.
- **UI-38** — Given the Voice tab of a draft agent, when *Realtime speech-to-speech* is selected, a realtime voice is chosen and a transfer number `+15557654321` is entered, then after Save draft and Publish the new version's snapshot contains `voice.pipeline: "realtime"`, that voice and `telephony.transfer_to`; an invalid number such as `0123` shows the API's validation error and nothing is saved; and the evaluator and extra-wait controls are disabled while Realtime is selected.
- **UI-41** — Given a business unit that does not allow realtime, when the Voice tab opens, then the *Realtime speech-to-speech* card is disabled with the Settings note and link and *Cascade* stays selected; after realtime is allowed in Settings, the card can be selected.
- **UI-22** — Given the Voice tab, when *Semantic detection* is selected, then the extra-wait and evaluator controls appear (hidden in *Normal detection*), and after Save draft and Publish the new version's snapshot contains the chosen values.
- **UI-07** — Given the Knowledge tab, when "Test search" is run with an unrelated query, then the panel shows "No answer — the agent would offer a specialist".
