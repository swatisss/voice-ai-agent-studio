---
type: Component Spec
title: Studio sign-in and roles
description: Two fixed demo accounts (admin and reviewer), a signed session cookie, the API guard that refuses admin-only requests from reviewers, and how the signed-in person is recorded on approvals, reviews and published versions.
status: draft
tags: [architecture, auth, security, roles]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-02T00:00:00Z" }
---

# Purpose

The Studio's human in the loop is a role, not a name typed in a box. A **reviewer** works the live and learning tasks; only an **admin** can change what callers hear ([CP-0034](/changes/cp-0034-studio-sign-in-and-roles.md)). The `/v1` API keeps its own API keys ([/api/public-api.md](/api/public-api.md)); telephony webhooks keep their signatures ([/architecture/telephony.md](/architecture/telephony.md)).

# Accounts and settings

| Email | Name | Role | Password setting |
|---|---|---|---|
| `admin@echomind.test` | Alex Admin | `admin` | `STUDIO_ADMIN_PASSWORD` |
| `reviewer@echomind.test` | Riley Reviewer | `reviewer` | `STUDIO_REVIEWER_PASSWORD` |

* **Sign-in is on** when at least one password setting is non-empty. An account whose password is unset cannot sign in.
* **Sign-in is off** otherwise: no cookie is needed and every request acts as `{name: "Studio", role: "admin"}`; request-body names (`decided_by`, `assignee`, `reviewer`, `by`) are used as before.
* `STUDIO_SESSION_SECRET` signs sessions. Unset, the key is derived from the two password settings, so sessions survive an API restart and end when a password changes.
* Settings come from the environment or `apps/api/.env`; passwords are never logged or returned.

# Session

* `POST /api/auth/login` `{email, password}` compares in constant time. Success sets cookie `studio_session` and returns `{user: {email, name, role}}`; anything else is 401 `bad_credentials` with no hint which part was wrong.
* The cookie value is `base64url(json{email, role, exp}).base64url(hmac_sha256)`; it is `HttpOnly`, `SameSite=Lax`, `Path=/`, `Secure` when the request came over HTTPS, and expires after **12 hours**. A tampered, expired or unknown-account cookie counts as no session.
* `POST /api/auth/logout` clears the cookie (204). `GET /api/auth/me` returns `{enabled, user}` (`user` is `null` without a session; with sign-in off it is the built-in admin).

# Guard

With sign-in on, every request whose path starts with `/api/` needs a session, except `/api/auth/*` and `/api/telephony/*`. Without one the answer is 401 `login_required`. `/healthz`, `/v1/*`, `/mock/*` and the static web files are not guarded. The voice WebSocket `/api/voice/{id}` is not guarded: it needs a call id, which only a signed-in `POST /api/calls` creates.

**Admin only.** A reviewer sending one of these gets 403 `admin_required` ("Only an admin can …") and nothing changes. Every other request is allowed for both roles; `GET` is never admin only.

| Area | Admin-only requests |
|---|---|
| Agents | `POST /api/agents`, `PUT /api/agents/{id}`, `POST /api/agents/{id}/publish` |
| Learning | `POST /api/proposals/{id}/approve` (with or without `force`) |
| Builder parts | `POST`, `PUT`, `DELETE` on `/api/tools…`, `/api/skills…`, `/api/personas…`, `/api/agents/{id}/scenarios`, `/api/scenarios/{id}`, `/api/use-cases…`, `/api/routing/cases…` |
| Knowledge | every `POST`, `PUT`, `DELETE` under `/api/knowledge/` except `POST /api/knowledge/search` |
| Settings | `PUT`, `DELETE` under `/api/tenant-settings`; `POST`, `PUT`, `DELETE` on `/api/api-keys…`, `/api/webhooks…`, `/api/phone-numbers…` |
| Members | `POST /api/members/{ref}/memory/erase`, `POST /api/members/{ref}/memory/{id}/restore` |

The reviewer keeps, for example: calls and conversations (start, message, end, feedback, rescore), console accept and resolve, scorecard reviews, `draft-fix`, `ignore`, action `done`, `dismiss` and `answer`, `POST /api/learning/run`, proposal `PUT`, `evaluate` and `reject`, test runs and routing runs.

# Who is recorded

With sign-in on, the signed-in user's name replaces the request body's value in: proposal `decided_by` (approve and reject), escalation `assignee` (accept), check review `reviewer`, action `closed_by` and cluster `human_answer_by`. Every new agent version records `published_by` (a builder publish or an approved fix); with sign-in off it is "Studio", and versions made before this change have `null`.

# Acceptance

- **AUTH-01** — Given sign-in on and no cookie, when `GET /api/agents` is sent, then the answer is 401 `login_required`; `/healthz` answers 200, `GET /api/auth/me` answers `{enabled: true, user: null}`, a signed Twilio webhook is not refused for lack of a session, and a `/v1` request with a valid API key is answered as before.
- **AUTH-02** — Given `STUDIO_REVIEWER_PASSWORD` set, when the reviewer signs in with a wrong password, then 401 `bad_credentials` and no cookie; with the right one, then the cookie is `HttpOnly` and `SameSite=Lax` and `GET /api/auth/me` returns Riley Reviewer with role `reviewer`; after logout, or with the cookie's payload altered, or 12 hours later, `GET /api/agents` is 401.
- **AUTH-03** — Given a signed-in reviewer, when they publish an agent, approve a ready proposal (also with `force`), save the agent draft, add a knowledge text, update tenant settings or erase a member's memory, then each answer is 403 `admin_required`, no agent version exists afterwards that did not exist before, and the proposal is still `ready`.
- **AUTH-04** — Given a signed-in reviewer, when they accept and resolve an escalation, review a judge check, answer an `answer_needed` action, start a learning run, reject a proposal and start a text call, then each request succeeds.
- **AUTH-05** — Given a signed-in admin, when they approve a proposal with body `decided_by: "Someone Else"`, then the proposal's `decided_by` is "Alex Admin" and the new version's `published_by` is "Alex Admin"; a builder publish by the admin also records "Alex Admin"; a reviewer's review of a check records "Riley Reviewer" whatever the body says.
- **AUTH-06** — Given sign-in off (no password set), then requests need no cookie, `GET /api/auth/me` returns `{enabled: false, user: {name: "Studio", role: "admin"}}`, body names are stored as sent, and a publish records `published_by: "Studio"`.
- **AUTH-07** — Given only `STUDIO_REVIEWER_PASSWORD` set, when signing in as the admin with any password, then 401 `bad_credentials`.
