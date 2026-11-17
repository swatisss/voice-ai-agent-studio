---
type: Component Spec
title: Agent Desk role
description: A third sign-in role for call-centre specialists - the console, escalated calls with masked details, escalation patterns they can comment on (feeding the learning loop), and read-only knowledge, agent settings and member memory; everything else is refused by the API; identifiers are masked in what they see and in application logs.
status: stable
tags: [architecture, auth, roles, console, learning, privacy]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-16T00:00:00Z" }
---

# Purpose

Two kinds of people use the platform. **Builders** (admin and reviewer, [/architecture/studio-auth.md](/architecture/studio-auth.md)) set up the AI agents and improve them. **Specialists** are the humans at the call centre who take over what the agents cannot finish. A specialist needs the queue, the caller's story, and a way to teach the agents; nothing else. The role is `specialist`, shown as **Agent Desk** ([CP-0047](/changes/cp-0047-agent-desk-role.md)).

What a specialist writes is the ground truth of the self-learning loop ([/architecture/fleet-learning.md](/architecture/fleet-learning.md)): the resolution note on an escalation and, new here, a **comment on an escalation pattern** (a cluster).

# Account

| Email | Name | Role | Password setting |
|---|---|---|---|
| `specialist@echomind.test` | Sam Specialist | `specialist` | `STUDIO_SPECIALIST_PASSWORD` |

Sign-in rules are those of studio-auth (an account whose password is unset cannot sign in; with every password unset sign-in is off and the built-in admin applies). The account is bound to one business unit, `STUDIO_SPECIALIST_TENANT` (default `northgate-health`). `GET /api/auth/me` returns `{user: {email, name, role, tenant_id}}` for the specialist (builders' `user` has no `tenant_id`).

# What the role may call

The API is **deny by default** for a specialist: a request not in this table is 403 `role_forbidden` ("Not available for your role") and changes nothing. A request for another business unit's data (`X-Tenant-Id` differing from the account's) is 403 `tenant_forbidden`; a missing header is treated as the account's unit.

| Area | Allowed |
|---|---|
| Session | `/api/auth/*`, `GET /api/tenants` (answers only the account's unit) |
| Console | `GET /api/escalations`, `GET /api/escalations/{id}`, `POST /api/escalations/{id}/accept`, `POST /api/escalations/{id}/resolve`, `POST /api/escalations/{id}/messages` (a typed reply to a text conversation, [/architecture/human-message-channel.md](/architecture/human-message-channel.md)); the event stream with topic `console` only; for a live voice call in a media room `POST /api/escalations/{id}/voice/join` and `GET /api/escalations/{id}/voice` ([/architecture/hosted-media-room.md](/architecture/hosted-media-room.md), LKH-15) |
| Phone | `POST /api/desk/phone-token`, `PUT /api/desk/phone-presence` (the specialist's browser as a phone, [/architecture/phone-warm-handover.md](/architecture/phone-warm-handover.md)) |
| Channel replies | `POST /api/escalations/{id}/messages` on an API or WhatsApp text conversation (CP-0049, [/architecture/whatsapp-channel.md](/architecture/whatsapp-channel.md)) |
| Calls | `GET /api/calls` and `GET /api/calls/{id}` **for escalated calls only** (the list is forced to calls with an escalation; any other call is 404 `call_not_found`) |
| Patterns | `GET /api/insights/clusters`, `GET /api/insights/clusters/{id}`, `GET /api/insights/clusters/{id}/comments`, `POST /api/insights/clusters/{id}/comments` |
| Knowledge | `GET /api/knowledge`, `GET /api/knowledge/{id}`, `GET /api/knowledge/sources`, `GET /api/knowledge/sources/{id}`, `POST /api/knowledge/search` |
| Agent settings | `GET /api/agents`, `GET /api/agents/{id}` (its `draft_config` carries the **published** setup, never an unpublished draft), `GET /api/agents/{id}/versions` |
| Member memory | `GET /api/members/{ref}/memory` (no export, restore or erase) |

Pattern responses for a specialist leave out money and learning internals: no `est_weekly_cost_usd`, `weekly_escalations`, proposals, evaluation results or fix drafts. They keep the name, description, counts, status (*Watching n of 5*, *Ready for a fix*, *Fixed*), the member escalated calls with their resolution notes, the comments and the fix line without per-week numbers.

Admins and reviewers keep their access and may also comment on a pattern. Their navigation no longer lists the console ([/ui/app-shell.md](/ui/app-shell.md)); the API still lets them accept and resolve an escalation, so scripts and the unattended walkthrough keep working.

# Masking

One module, `voiceai/mask.py`, with two functions and one rule set:

* `member_ref("NGH-410237")` → `NGH-•••237`; `phone("+447700900123")` → `•••0123`; `email("meera@example.com")` → `m***@example.com`.
* `text(s)` masks, anywhere inside free text: member references (`[A-Z]{2,5}-\d{6}`), email addresses, telephone numbers and any run of 6 or more digits. It is best effort on transcripts: it hides identifiers, not names or health details.

It is applied:

1. **To everything a specialist receives.** The response body of every allowed request is passed through `text()` on its string values and `member_ref()` / `phone()` / `email()` on the known identifier fields, so the Studio cannot show more than the API sent. A member reference in a request path is accepted as given (`/api/members/NGH-410237/memory` is reached from a link that carries it) and masked in the answer.
2. **To the specialist's own writing.** A resolution note and a pattern comment are masked with `text()` before they are stored, so the drafter, the Evidence table and every other reader see the masked text.
3. **To application logs, for everyone.** A logging filter on the `voiceai` loggers masks the formatted message with `text()`. Request logs never include request or response bodies; the audit line of a call (who published the version) is unchanged.

Stored call events keep what was said, as today; builders see them as before ([/ui/calls.md](/ui/calls.md)).

# Pattern comments

A specialist (or admin or reviewer) can add a comment to any cluster of the account's business unit: "What do you tell callers about this?".

* `POST /api/insights/clusters/{id}/comments` `{text}` (10 to 1000 characters after trimming; 422 `comment_too_short` / `comment_too_long`) → the comment `{id, cluster_id, author, author_role, text, created_at}`; 404 for an unknown cluster. The author is the signed-in user's name (with sign-in off, "Studio"). The text is masked before it is stored. Publishes `cluster.updated` (topic `insights`).
* `GET /api/insights/clusters/{id}/comments` → `{items: [comment]}`, oldest first. Comments are append-only; none can be edited or deleted in the Studio.
* **Feeds learning.** A comment is the same kind of evidence as a resolution note: the drafter's evidence gets one line per comment, "Specialist comment (Sam Specialist): …" ([/prompts/fix-draft.md](/prompts/fix-draft.md)); a `missing_knowledge` cluster with a comment of at least 20 characters has a human answer, so `needs_answer` is false and `draft-fix` is allowed ([/architecture/learning-actions.md](/architecture/learning-actions.md)); an open `answer_needed` action for it closes. A comment does not change a cluster's `signal_count` and does not make it ready sooner.
* The cluster detail for builders shows the comments under Evidence ([/ui/insights.md](/ui/insights.md)).

# Acceptance

- **DESK-01** — Given sign-in on and `STUDIO_SPECIALIST_PASSWORD` set, when the specialist signs in with the right password, then `GET /api/auth/me` returns Sam Specialist with role `specialist` and `tenant_id: "northgate-health"`; with a wrong password 401 `bad_credentials`; with only `STUDIO_ADMIN_PASSWORD` set the specialist cannot sign in.
- **DESK-02** — Given a signed-in specialist, when they send `GET /api/dashboard/summary`, `GET /api/insights/inbox`, `GET /api/evaluation/...`, `PUT /api/agents/{id}`, `POST /api/knowledge/text`, `GET /api/tenant-settings`, `GET /api/members/{ref}/memory/export` or `POST /api/calls`, then each is 403 `role_forbidden` and nothing changes; an allowed request (`GET /api/escalations`, `GET /api/agents`, `GET /api/knowledge`, `POST /api/knowledge/search`, `POST /api/escalations/{id}/messages` on an accepted text escalation) succeeds.
- **DESK-03** — Given a specialist and a request with `X-Tenant-Id` of another business unit, then 403 `tenant_forbidden`; `GET /api/tenants` lists only the account's unit.
- **DESK-04** — Given escalated and non-escalated calls, when the specialist lists calls, then only escalated calls are returned; `GET /api/calls/{id}` of a call without an escalation is 404; an administrator sees both.
- **DESK-05** — Given a call whose transcript says "my number is NGH-410237, email meera@example.com, phone 07700900123", when the specialist reads the call and its escalation packet, then the identifiers are `NGH-•••237`, `m***@example.com` and `•••0123` everywhere in the response; the same call read by the admin is unchanged.
- **DESK-06** — Given a specialist resolving an escalation with a note that contains `NGH-410237`, then the stored `resolution_note` contains `NGH-•••237` and no full reference.
- **DESK-07** — Given a log line formatted with a member reference, an email address and a telephone number, then the line written by the `voiceai` loggers contains none of the three in full.
- **DESK-08** — Given a specialist's pattern response, then it has no cost, weekly counts, proposals or evaluation fields, and it lists the cluster's escalated calls with their notes; a builder's response is unchanged.
- **DESK-09** — Given a cluster, when the specialist posts a comment of 9 characters, then 422 `comment_too_short`; with 60 characters it is stored with their name, role and masked text, `GET …/comments` lists it, and a `cluster.updated` event is published; the admin can also comment; a reviewer's comment records "Riley Reviewer".
- **DESK-10** — Given a ready `missing_knowledge` cluster whose calls have no resolution note, when a specialist comments with 30 characters, then `needs_answer` is false, its `answer_needed` action is closed, and the drafter's evidence contains "Specialist comment (Sam Specialist): …"; a comment of 15 characters is stored but `needs_answer` stays true; no comment changes `signal_count`.
- **DESK-11** — Given an admin or reviewer, then `POST /api/escalations/{id}/accept` and `resolve` still succeed (AUTH-04).
- **DESK-12** — Given a signed-in specialist, when they call `POST /api/desk/phone-token` and `PUT /api/desk/phone-presence`, then both are allowed (not `role_forbidden`) and scoped to their own business unit; a reply to an escalated WhatsApp conversation through `POST /api/escalations/{id}/messages` is allowed and the customer's address appears masked (`address_last4`) in everything the specialist reads (WA-12).