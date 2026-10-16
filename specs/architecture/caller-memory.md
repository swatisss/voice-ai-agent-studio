---
type: Component Spec
title: Caller memory
description: How the agent remembers verified callers across calls - a structured note after each call, a background "dream" that consolidates notes into a versioned caller profile, recall at call time, privacy rules and the swappable MemoryProvider.
status: draft
tags: [architecture, memory, privacy, learning]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-16T00:00:00Z" }
---

# Purpose

Today every call starts from nothing. Caller memory lets an agent greet and serve a returning caller with what earlier calls taught it (preferences, household, open issues) without the caller repeating themselves.

It follows a two-stage design inspired by consolidating memory offline ("dreaming"):

| Stage | When | What it does |
|---|---|---|
| **1. Capture** | right after a call ends | An LLM turns the transcript into one small structured **call note**. Notes never change the profile. |
| **2. Dream** | when a caller has `dream_after_notes` (default 10) notes waiting | An LLM reads the caller's current profile plus the waiting notes and returns **changes**: add, update, confirm, retire. Code validates and applies them as a **new profile version**. |
| **3. Recall** | during a call | The agent's system prompt receives the consolidated profile (plus the few newest not-yet-dreamed notes) as `{{caller_memory}}`. |

The profile stays small and deduplicated because only the dream writes it; raw notes are the audit trail and are deleted after the retention period. Decisions and alternatives are in [/decisions/adr-0008-caller-memory.md](/decisions/adr-0008-caller-memory.md).

# Who is "the caller"

Memory is keyed by **tenant + `member_ref`** (for example `EVG-482913`). A `member_ref` is known only after a verification tool returned `verified: true` in the call ([/architecture/tools-and-skills.md](/architecture/tools-and-skills.md)). Consequences:

* **Notes are written only for calls with a verified member.** Unverified calls, simulation and eval calls ([/architecture/evaluation.md](/architecture/evaluation.md)), `internal`-mode calls (staff, [/architecture/call-modes.md](/architecture/call-modes.md)) and calls of agents with `memory.enabled: false` write nothing.
* A profile is shared by all agents of the tenant that have memory enabled; every fact records the agent and call it came from.
* **Caller ID is a hint, never an identity.** `POST /api/calls` accepts an optional `caller_phone`. It is normalised to digits and stored only as a salted SHA-256 hash (`MEMORY_PHONE_SALT`, never the number). When a verified call carries a phone hash, the hash is added to that member's profile. A later call with the same hash and exactly one matching profile gets the **hint recall** below.

# Memory facts

A profile holds a list of facts (JSON):

| Field | Meaning |
|---|---|
| `id` | stable id, `f_` + 8 hex chars, assigned by code |
| `text` | one short sentence, ≤ 200 chars, third person ("Prefers calls after 5 pm.") |
| `kind` | `preference` · `contact` · `household` · `open_issue` · `history` · `other` |
| `sensitivity` | `low` (communication preferences: language, pace, channel, time of day) · `normal` (name, household, history, open issues) · `high` (health, claims, money) |
| `basis` | `stated` (the caller said it or a tool returned it) or `inferred` (the model concluded it) |
| `first_seen_at`, `last_confirmed_at` | timestamps; confirmation moves `last_confirmed_at` |
| `expires_at` | nullable; `open_issue` facts default to 30 days after last confirmation |
| `source_note_ids` | notes that support the fact |

Never stored: full member IDs, dates of birth, SSNs, card or account numbers, addresses, phone numbers or e-mail addresses. A deterministic **scrub** runs on every note and every dream output before saving: digit runs of 6 or more digits, date-of-birth patterns, e-mail addresses and `@handle`-like strings are removed from the text, and a fact whose text becomes empty is dropped. Health details are kept only when the caller stated them, only with `sensitivity: high`, and are never inferred.

# Capture (stage 1)

`end()` ([/architecture/agent-runtime.md](/architecture/agent-runtime.md)) enqueues job `capture_call_note` (dedupe key `capture_call_note:{call_id}`) after `analyze_call`, when the call qualifies (see above) and has at least one caller turn.

1. Load the call transcript and tool summaries; call the `memory` role with [/prompts/memory-capture.md](/prompts/memory-capture.md); validate the JSON.
2. Scrub, then store a `call_notes` row: `summary` (≤ 300 chars) and candidate `facts` (same fields as above, without ids).
3. If the call carried a phone hash, add it to the member's current profile (as a new version, source `capture`) when it is not there yet.
4. Count the member's `pending` notes; if the count is ≥ `dream_after_notes`, enqueue `dream_profile` (dedupe key `dream_profile:{member_ref}:{current profile version}`).

A capture failure never affects the call or its analysis; it retries per [/architecture/jobs-and-events.md](/architecture/jobs-and-events.md).

# Dream (stage 2)

Job `dream_profile` `{member_ref}`; also started by `POST /api/memory/members/{member_ref}/dream` (trigger `manual`).

1. Load the current profile (facts, suppressed list) and up to 25 oldest `pending` notes; none pending → run `skipped`.
2. Call the `memory` role with [/prompts/memory-dream.md](/prompts/memory-dream.md). The model returns a list of **changes**, never a rewritten profile: `add {fact}`, `update {fact_id, text, …}`, `confirm {fact_id}`, `retire {fact_id, reason}`, and `contradictions` it noticed.
3. **Code validates and applies** the changes: unknown `fact_id`s are ignored; facts matching a `suppressed` entry are not added; scrub runs; `sensitivity: high` facts require `basis: stated`; `expires_at` defaults are applied.
4. **Cap.** If more than `max_items` facts remain, retire the lowest-value ones first: expired, then inferred and unconfirmed longest, then oldest `history`.
5. Write a new `caller_profiles` row (`version = previous + 1`, `is_current` moves to it) and a `dream_runs` row holding the change list (the diff), the contradictions, tokens and cost; mark the used notes `dreamed`.
6. Publish `memory.updated`.

If the model call or validation fails, the run is `failed`, the profile is **unchanged**, the notes stay `pending` and the job retries. A retired fact is kept in the version history, not in the current profile.

# Recall (stage 3)

Recall happens at two moments of a call and is cached in the session (never per turn):

| Moment | Level | What is loaded |
|---|---|---|
| Call start, inbound agent, `caller_phone` hash matches exactly one profile | `hint` | only facts with `sensitivity: low`, labelled *unverified*. No name, no account detail. |
| A verification tool succeeds with `member_ref` | `verified` | all non-expired facts of that member's current profile (`low`, `normal`, `high`), plus the summaries of up to **3 newest `pending` notes** ("recent calls not yet consolidated"), so a caller is remembered from the very next call rather than after ten. |

If a hint was loaded for another profile than the verified member's, the hint is discarded: the next turn contains only the verified member's memory. Expired facts are never injected. Agents with `memory.enabled: false` get no memory block and no hint lookup.

The block is rendered into the system prompt ([/prompts/agent-system-prompt.md](/prompts/agent-system-prompt.md)) as `- <text>` lines; inferred facts are prefixed `(inferred, not confirmed)`; hint-level facts sit under the heading "Unverified hint". The prompt tells the agent to use memory naturally and only where it helps, never to read a stored fact back as a surprise, to confirm inferred facts before relying on them, and never to treat memory as identity verification or as an approved source for plan rules.

`CallState` gains `memory_level` (`none` · `hint` · `verified`) and `memory_fact_ids` (facts shown to the model this call) so the call detail can show what memory was used.

# Retention and deletion

* `retention_days` (default 365): a fact not confirmed within the period is retired by the next dream or purge; `dreamed` notes older than the period are deleted. Job `purge_expired_memory` runs once per app start and once per 24 h while the process lives (dedupe key `purge_expired_memory:{date}`); recall also ignores expired facts regardless of the job.
* **Delete a fact** (staff, console): a new version without it; the removed text is recorded in `suppressed` so a later dream does not re-add it. `suppressed` entries are removed with the profile and by retention.
* **Delete a member's memory**: removes the member's `call_notes`, all `caller_profiles` versions (including `suppressed` and phone hashes) and `dream_runs` in one transaction; queued capture and dream jobs for that member find nothing to do.
* Deleting a call or knowledge does not delete derived memory; memory deletion is its own action.

# MemoryProvider

The runtime and jobs depend only on this interface (`voiceai/memory/provider.py`); the default implementation is `SqlMemoryProvider` over the tables in [/data/data-model.md](/data/data-model.md). Selected by `MEMORY_PROVIDER` (`sql` default). Other backends, such as mem0, may be added later behind it with a CP; none is built now.

| Method | Behavior |
|---|---|
| `recall(tenant_id, member_ref, now)` → `Recall` | verified-level facts + newest pending notes, expired removed |
| `recall_hint(tenant_id, phone_hash, now)` → `Recall \| None` | low-sensitivity facts when exactly one profile matches |
| `add_note(tenant_id, note)` → note | stores a scrubbed note, returns the pending count |
| `consolidate(tenant_id, member_ref, changes, run)` → profile | applies validated changes as a new version |
| `list_members`, `get_member`, `edit_fact`, `delete_fact`, `delete_member` | console operations |

# Configuration

Agent config block `memory` ([/data/agent-config.md](/data/agent-config.md)): `enabled` (default `false`), `dream_after_notes`, `max_items`, `retention_days`. LLM role `memory` ([/architecture/llm-gateway.md](/architecture/llm-gateway.md)). Environment: `MEMORY_PROVIDER`, `MEMORY_PHONE_SALT` (a default dev salt is used locally; deployment sets a secret).

# Acceptance

- **MEM-01** — Given a memory-enabled agent and an ended call with a verified member and at least one caller turn, when `end()` runs, then one `capture_call_note` job exists (also after a second `end()`), and after it runs one `call_notes` row exists for the member with status `pending` and a summary of at most 300 characters.
- **MEM-02** — Given an unverified call, a simulation or eval call, an `internal`-mode call, or an agent with `memory.enabled: false`, when the call ends, then no `capture_call_note` job is queued and no note exists.
- **MEM-03** — Given a model output containing a date of birth, a 9-digit member id, an e-mail address and a phone number, when the note is stored, then none of them appears in `summary` or any fact text, and a fact that becomes empty is dropped.
- **MEM-04** — Given 9 pending notes for a member and `dream_after_notes: 10`, when a tenth note is stored, then one `dream_profile` job is queued; with only 9, none is; two tenth-note events queue one job.
- **MEM-05** — Given a profile with the fact "Prefers calls after 5 pm" and notes that repeat it, contradict it ("now prefers mornings") or add a new preference, when the dream runs, then the repeat only moves `last_confirmed_at`, the contradicted fact is retired with a reason and the new one added, the profile `version` is previous + 1, and the `dream_runs` row lists each change; a change naming an unknown `fact_id` is ignored.
- **MEM-06** — Given the `memory` role raises or returns invalid JSON twice, when the dream runs, then the run is `failed` with the error, the current profile is unchanged, the notes are still `pending`, and the job is retried per JB-01/JB-02.
- **MEM-07** — Given a profile at `max_items` and a dream that adds two facts, then the profile still holds `max_items` facts, the retired ones being expired first, then inferred-unconfirmed, then the oldest `history`; a `stated` fact is never retired by the cap while an inferred one remains.
- **MEM-08** — Given a fact whose `expires_at` has passed and a `dreamed` note older than `retention_days`, then recall omits the fact and `purge_expired_memory` deletes the note and retires facts not confirmed within `retention_days`.
- **MEM-09** — Given a memory-enabled agent and a profile with two facts and a pending note, when the caller verifies as that member, then the next system prompt contains both facts and the note summary, `memory_level` is `verified`, and `memory_fact_ids` lists the two facts.
- **MEM-10** — Given an inbound call with a `caller_phone` whose hash matches exactly one profile that has `low` and `normal` facts, when the call starts, then the system prompt contains only the `low` facts under "Unverified hint", `memory_level` is `hint`, and no name, `normal` or `high` fact is present; with two matching profiles or none there is no hint.
- **MEM-11** — Given a hint loaded for member A, when the caller verifies as member B, then B's memory is loaded and none of A's facts is in the following prompt.
- **MEM-12** — Given an `inferred` fact and a `stated` fact, when memory is rendered, then the inferred line is prefixed `(inferred, not confirmed)` and the stated line is not; `high`-sensitivity facts are never rendered at hint level.
- **MEM-13** — Given a real model and a profile with an inferred preference, then the agent confirms it ("I have you down as … is that right?") instead of stating it as fact, and never reads a stored fact back unprompted as a surprise (checked by hand with a real model; prompt rule in [/prompts/agent-system-prompt.md](/prompts/agent-system-prompt.md)).
- **MEM-14** — Given memory for member M in tenant A, when tenant B requests `GET /api/memory/members/M`, lists members, deletes it, or has a call that verifies as M, then B sees 404 or an empty list and no tenant-A fact is ever in tenant B's prompt.
- **MEM-15** — Given a profile fact, when a person edits its text or deletes it, then a new profile version exists, the deleted fact's text is in `suppressed`, and a later dream whose notes mention it does not add it again.
- **MEM-16** — Given a member with notes, three profile versions and dream runs, when `DELETE /api/memory/members/{member_ref}` is called, then no `call_notes`, `caller_profiles` or `dream_runs` rows remain for that member, a queued dream for them ends without creating anything, and the next call recalls nothing.
- **MEM-17** — Given `POST /api/memory/members/{member_ref}/dream`, then it returns 409 `nothing_to_consolidate` with no pending notes, otherwise `{job_id}` and a `manual` run follows.
- **MEM-18** — Given a fake `MemoryProvider` registered through `MEMORY_PROVIDER`, when a call is captured and recalled, then the runtime and jobs work with no SQL memory tables touched and no network.
- **MEM-19** — Given a call with `caller_phone`, then neither the number nor any digits of it are stored in any table or call event; only its salted hash is, in `caller_profiles.phone_hashes` and `calls.meta`.
