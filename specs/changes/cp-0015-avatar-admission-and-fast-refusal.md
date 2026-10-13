---
type: Change Proposal
title: CP-0015 Avatar admission control and fast refusal
description: "A refused or over-limit Simli session degrades at once to an ordinary video call, our own concurrency is capped below the vendor's, and no vendor session outlives the process."
status: stable
cp_state: implemented
tags: [video, avatar, simli, reliability]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-13T00:00:00Z" }
---

# Why

The avatar "got stuck" in the first real runs. One cause was a dev-launcher bug (every call restarted its own server and orphaned a vendor session, DEV-07). The other is in the avatar itself: when Simli refuses a session (rate limit, concurrent-session cap) its SDK turns that into an internal event and lets the socket die without raising. [AV-05](/architecture/avatar.md) only noticed after the 5 s return watchdog, so the agent's first words were swallowed and replayed late, with a burst of "Websocket closed" log lines. Nothing bounded how many sessions this process opens, and nothing closed them at shutdown.

# What changes

1. **A refusal is detected when the session opens (AV-10).** The stage listens for the vendor's error event and, after opening, waits briefly for the first video frame before it starts consuming speech. An explicit refusal fails the stage before the welcome; silence with no refusal is trusted, so a slow first frame never costs a call its face.
2. **Our own session cap (AV-11).** `AVATAR_MAX_SESSIONS` (default 1) bounds live vendor sessions in this process. A call over the cap is an ordinary video call with a placeholder tile and never contacts the vendor.
3. **Sessions do not outlive the process (AV-12).** Shutdown closes every open vendor session.

# Decisions taken while drafting

* `STOP` is not treated as a failure: the SDK maps its `ENDFRAME` marker to it, which appears to end an utterance. Only `ERROR` (which includes the rate-limit message) is.
* The cap is per process. Across several instances it is a per-instance share of the vendor limit; a shared counter is a follow-up if the service ever scales out.
* Default 1 is deliberately conservative for a free plan; raise it to the plan's limit.

# Affected specs

Updated: [/architecture/avatar.md](/architecture/avatar.md) (AV-10…AV-12, configuration, failure section), [/build/task-plan.md](/build/task-plan.md) (T33).

# Acceptance criteria

New: **AV-10…AV-12**. No ID is changed or retired.

# Tasks

1. **T33** - refusal listener and proof of life, session cap, shutdown close, `AVATAR_MAX_SESSIONS` setting and `.env.example`, tests - covers AV-10, AV-11, AV-12.

# Risks and rollout

* **Unverified against the real vendor.** The error event is wired from the SDK source; no test reaches Simli. If the event name or timing differs, the 5 s watchdog (AV-05/AV-09) still catches a refusal, just later.
* **Cap too low** hides the face from concurrent callers; raise `AVATAR_MAX_SESSIONS`.
* **Rollback:** set `AVATAR_MAX_SESSIONS` high; the listener only adds an earlier failover.

# Out of scope

Rendering in the caller's browser, a no-vendor animated tile, a cross-instance counter, a face per persona.
