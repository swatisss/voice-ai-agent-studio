---
type: Change Proposal
title: CP-0034 Studio sign-in with two roles - admin and reviewer
description: The Studio gets a sign-in page and two fixed demo accounts; reviewers work the human-in-the-loop tasks (console, answers, call reviews, learning runs, rejecting fixes) while only an admin can change what a live agent does (publish, approve a fix, edit agents, knowledge, tools and settings), enforced by the API and recorded as who did it.
status: stable
cp_state: implemented
tags: [auth, security, api, ui, healthcare]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-02T00:00:00Z" }
---

# Why

The Studio has no sign-in: a business-unit switcher stands in ([scope](/product/scope.md)), so anyone who can open it can publish an agent, approve a learning fix or erase a member's memory. For a regulated buyer the first question about self-learning is "who is allowed to change what the agent tells callers?" The [compliance note](/product/healthcare-compliance.md) lists access controls as a production gap, and the hackathon pitch (2026-11-04) needs to show the human in the loop as a real role: a specialist works the escalations and teaches the agent, and only an admin can put a change in front of callers.

Decisions from the product owner (2026-11-02): a real sign-in with two seeded demo accounts, the API enforces the roles (not only hidden buttons), no SSO; the reviewer is the human in the loop and does not need admin rights; publishing to a live agent, including approving a learning fix, is admin only.

# What changes

1. **Sign-in.** A sign-in page with two fixed, synthetic accounts: **Alex Admin** (`admin@echomind.test`, role `admin`) and **Riley Reviewer** (`reviewer@echomind.test`, role `reviewer`). Passwords come from `apps/api/.env` (`STUDIO_ADMIN_PASSWORD`, `STUDIO_REVIEWER_PASSWORD`). A session is a signed, HTTP-only cookie valid for 12 hours. Sign-in is on as soon as one password is set; with none set the Studio works as today and every request acts as admin "Studio" (so local tests and the fake demo are unchanged).
2. **Two roles, enforced by the API.**
   * **Reviewer (human in the loop):** sees everything; makes test calls; accepts and resolves escalations in the agent console; answers *Answer needed*; reviews scorecard checks (which calibrates the judge); closes or dismisses learning actions; runs learning, drafts, edits, evaluates and **rejects** fixes; starts test and routing runs.
   * **Admin:** everything a reviewer does, and the only role that can change what callers hear: create, edit and **publish** agents; **approve** a fix (which publishes it), including *Publish anyway*; edit knowledge, tools, skills, personas, test scenarios and use cases; settings, provider keys, API keys, webhooks and phone numbers; erase or restore member memory.
   * An admin-only request from a reviewer is refused with 403 `admin_required` and changes nothing; a request without a valid session gets 401 `login_required`.
3. **Who did it.** With sign-in on, the API records the signed-in person, not a name typed in the request body, as the approver or rejecter of a fix, the assignee of an escalation, the reviewer of a check, the person who closed or answered an action, and the **publisher of every agent version** (new `agent_versions.published_by`).
4. **In the UI.** The sidebar shows who is signed in, the role and **Sign out**. Admin-only buttons stay visible to a reviewer but are disabled with the hint "Admin only", so the demo can show the boundary.

# Affected specs

* [/architecture/studio-auth.md](/architecture/studio-auth.md) (new) - accounts, session, guard, role table, who is recorded; AUTH-01…AUTH-07
* [/product/scope.md](/product/scope.md) - Studio sign-in with two roles moves into scope; SSO, more roles and user management stay out
* [/product/healthcare-compliance.md](/product/healthcare-compliance.md) - rule 12 (only an admin publishes); the access-control gap narrows
* [/api/rest-api.md](/api/rest-api.md) - `/api/auth/*`, 401 and 403 in the conventions, request-body names ignored when sign-in is on
* [/data/data-model.md](/data/data-model.md) - `agent_versions.published_by`; DM-14
* [/ui/app-shell.md](/ui/app-shell.md) - sign-in page, signed-in user and Sign out, admin-only controls; UI-69, UI-70

# Acceptance criteria

Defined in the specs above: **AUTH-01…AUTH-07**, **DM-14**, **UI-69**, **UI-70**.

# Tasks

1. Spec edits (this CP).
2. `voiceai/auth.py`: settings, accounts, signed session cookie, `/api/auth/login|logout|me`, the guard middleware with the admin-only table, `current_user` for routes; CORS with credentials — AUTH-01…AUTH-04, AUTH-07.
3. Routes record the signed-in user (approve, reject, accept, review, action done, dismiss and answer, publish); column `agent_versions.published_by` and its upgrade — AUTH-05, AUTH-06, DM-14.
4. Web: `/login/` page, `fetch` and `EventSource` with credentials, redirect on 401, the user block in the sidebar, `useMe()` and disabled admin-only controls — UI-69, UI-70.
5. `.env.example` lines; demo walkthrough uses the two accounts. (`dev.py --check` reporting sign-in was dropped: the launcher spec does not cover it.)
6. Tests in `tests/test_studio_auth.py`.

# Risks and rollout

* Existing databases get `published_by` as null for older versions (shown as "unknown").
* With sign-in on, the web dev server (port 3000) calls the API (port 8000) with credentials; both are `localhost`, so the `SameSite=Lax` cookie is sent; CORS must allow credentials for the configured origins.
* The fake demo runner and the test suite run with sign-in off; `tests/test_studio_auth.py` turns it on.
* The passwords live in `.env` in plain text; this is a demo control, not production identity.

# Out of scope

SSO and OAuth, user management (adding users, changing passwords), more than two roles, per-business-unit permissions, password reset, lockout after failed attempts, audit-log export, signing in on the voice WebSocket (it is reached only with a call id created by a signed-in `POST /api/calls`).
