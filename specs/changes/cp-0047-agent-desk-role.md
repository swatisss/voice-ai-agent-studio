---
type: Change Proposal
title: CP-0047 Agent Desk role - a workspace for call-centre specialists
description: A third sign-in role for the humans who take over escalations - the console, escalated calls with masked details, comments on escalation patterns that feed the learning loop, and read-only knowledge, agent settings and member memory - with the console leaving the builders' navigation.
status: stable
cp_state: implemented
tags: [auth, roles, console, learning, privacy, ui]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-16T00:00:00Z" }
---

# Why

The Studio has one workspace for two kinds of people. Builders set up and improve the AI agents; call-centre specialists only take over the calls the agents cannot finish. Today a specialist would sign in as "reviewer" and see ten menu items, Settings and the agent editor among them, and the API would allow most of it. The owner wants a role for specialists that shows the bare minimum, read-only apart from the console actions, and a way for them to teach the agents beyond one resolution note at a time. Research (agent-desktop practice; Intercom Fin's split between its setup surface and the Inbox where humans pick up an escalation) supports one consolidated, role-tailored desk for specialists and a separate setup surface for builders.

# What changes

* New role `specialist`, shown as **Agent Desk**, with the demo account Sam Specialist (`specialist@echomind.test`, `STUDIO_SPECIALIST_PASSWORD`), bound to one business unit. It signs in to `/console/`.
* The API is deny by default for the role: only the console, escalated calls, escalation patterns (with comments), read-only knowledge, agent settings and member memory are reachable; every other request is 403 `role_forbidden`; another business unit is 403 `tenant_forbidden`.
* **Masking.** Everything a specialist receives has member references, emails, telephone numbers and long digit runs masked; their own notes and comments are masked before storage; application logs mask the same identifiers for everyone.
* **Comments on a pattern.** New `cluster_comments` table and `GET`/`POST /api/insights/clusters/{id}/comments`. A comment is evidence for the fix draft like a resolution note, and satisfies the "a person must say it" rule of `answer_needed`. Builders see the comments in Insights and can add their own.
* **Navigation.** The Agent console item leaves the admin's and reviewer's sidebar (nine items); the specialist's sidebar has five: Agent console, Escalated calls, Patterns, Knowledge, Agents. Admin and reviewer can still call accept/resolve on the API, so scripts and the unattended walkthrough are unchanged.
* **Demo.** The console steps of Acts 4 and 6 move to the specialist window, and Act 6 gains a beat: the specialist comments on the cluster and the drafted fix carries it.

# Affected specs

* [/architecture/agent-desk.md](/architecture/agent-desk.md) - new: role, allow-list, masking, pattern comments (DESK-01..DESK-11)
* [/ui/agent-desk.md](/ui/agent-desk.md) - new: the specialist's workspace (UI-77..UI-82)
* [/architecture/studio-auth.md](/architecture/studio-auth.md) - third account, `tenant_id` in `me`, landing by role
* [/ui/app-shell.md](/ui/app-shell.md) - navigation by role, badge, UI-29 now nine items
* [/ui/agent-console.md](/ui/agent-console.md) - signed-in name, masking
* [/ui/calls.md](/ui/calls.md), [/ui/member-memory.md](/ui/member-memory.md) - reduced specialist views
* [/ui/insights.md](/ui/insights.md) - Specialist comments under Evidence
* [/data/data-model.md](/data/data-model.md) - `cluster_comments`, DM-16, 39 tables
* [/api/rest-api.md](/api/rest-api.md) - comments endpoints, role note
* [/architecture/fleet-learning.md](/architecture/fleet-learning.md), [/architecture/learning-actions.md](/architecture/learning-actions.md), [/prompts/fix-draft.md](/prompts/fix-draft.md) - comments as evidence and as human answers
* [/product/demo-walkthrough.md](/product/demo-walkthrough.md) - specialist window, comment beat

# Acceptance criteria

New: DESK-01 to DESK-11 ([/architecture/agent-desk.md](/architecture/agent-desk.md)), UI-77 to UI-82 ([/ui/agent-desk.md](/ui/agent-desk.md)), DM-16. Changed: UI-29 (nine items for builders), DM-01 (39 tables). AUTH-04 stays true (reviewer can still accept and resolve through the API).

# Tasks

1. Spec edits (done in this CP).
2. `auth.py`: third user, `tenant_id`, allow-list and tenant guard for the role, role-based landing in `me`; `.env.example`, `setup.py`, `scripts/demo/fake_server.py` (password) - covers DESK-01..03.
3. `mask.py`, response masking for the role, masking of notes and comments on write, logging filter - covers DESK-04..07.
4. Role-shaped responses for calls and clusters (escalated only, no cost or proposals) - covers DESK-04, DESK-08.
5. `cluster_comments` model, startup table check, routes, evidence in the fleet and learning code, `needs_answer` and action closing - covers DESK-09..11, DM-16.
6. Web: role-aware shell and redirects, `/patterns/`, `/patterns/cluster/`, `/knowledge/`, `/agents/view/`, read-only member memory, comments in Insights, console name from session - covers UI-77..UI-82.
7. Tests citing the IDs; `demo_walkthrough.py` signs in as the specialist for the console steps and adds the comment beat; update `docs/demo-guide.md` (specialist window, comment steps) and the acceptance baseline for UI-77..UI-82 if not click-tested.
8. `specs/log.md`, set specs `stable`, CP `implemented`.

# Risks and rollout

* **Masking is best effort on free text.** It hides identifiers (references, emails, phone numbers, 6+ digit runs); it does not find names or health details in a transcript. The compliance page should not claim more. Claim ids such as `CL-70231` are not masked.
* **Deny by default can break a page.** The specialist's pages must use only the listed endpoints; a test calls each page's requests as the specialist.
* **Existing databases:** one new table, created at startup; no data change. Existing escalations and clusters work as before.
* **Demo:** the console moves to a third window (specialist). With sign-in off the console item stays in the nav, so local development is unchanged.

# Out of scope

* A team-lead or supervisor role (queue health, reassigning, breaks) and agent presence (Available / On break).
* Real accounts, SSO, per-specialist queues and skill-based routing; accounts stay the fixed demo accounts.
* Editing or deleting comments; moderating them.
* Masking stored call events and transcripts for builders; this CP masks what the specialist receives and what is logged.
* Showing agent memory beyond the existing read-only member memory page.
