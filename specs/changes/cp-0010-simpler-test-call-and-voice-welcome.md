---
type: Change Proposal
title: CP-0010 Simpler Test call page and a spoken welcome in voice calls
description: Remove the use-case card gallery from Test call (the agent select is the only selector), move Talk | Type into the call card, hide technical details behind a toggle, and make voice calls open with the agent's spoken welcome instead of waiting for the tester to speak.
status: stable
cp_state: implemented
tags: [ui, test-call, voice]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-07T00:00:00Z" }
---

# Why

Product-owner feedback after using Test call with business (non-technical) testers:

* The page offers two ways to choose what to test: the **agent select** and a **gallery of seven use-case cards**. Cards only pick an agent (four agents serve the seven use cases) and then filter two lists. They push the conversation below the fold and add nothing a plain line of text could not say.
* **Talk | Type** sits at the very top of the page, far from the place where the tester talks or types.
* **Activity** (tool chips, knowledge searches) and the **Call** card (call id, tokens, LLM cost, median latency) are for builders. Business testers see them all the time.
* In **Talk** mode the tester does not get the welcome: after **Start call** the agent only seems to speak once the tester does. The specs already promise the greeting ([VO-01](/architecture/voice-pipeline.md), [call modes](/architecture/call-modes.md)). Measured against a scratch server with real speech synthesis: with a silent microphone the whole welcome plays (about 10 s); when the agent's own voice reaches the microphone (open speakers, no headset) the server hears a "caller" and **interrupts the welcome about a second in**, then answers its own echo as if it were a caller turn. VO-01 was only ever on the by-hand list, and no test could catch it.

What stays, by decision: the agent select, **Live controls** (change persona during a call; Normal / Semantic turn detection), and the mode labels **Inbound / Outbound / Internal**.

# What changes

1. **No use-case gallery.** The agent select (published agents) is the only selector. Beside it: the version badge, the mode badge (Inbound / Outbound / Internal) and a plain-text line **"Handles:"** listing the titles of the use cases that agent serves, from the existing `GET /api/use-cases` (matched on `agent_id`).
2. **Test script card** (right column, replaces the *Demo callers* card). For the selected agent it lists, per use case, only its **starting phrase** (the first sample phrase). Demo callers are no longer shown on screen — member IDs and dates of birth live in the demo data and the demo script. The phrase is clickable (fills the message box) only while a chat is running; otherwise it is plain text to read aloud, so there are no dead, disabled buttons.
3. **Talk | Type moves into the call card** (its header, next to Start / End). It can be changed between calls; during a call it is disabled with the hint "End the call to switch". The page's top row no longer carries the tabs.
4. **Technical details switch** at the top right of the page, **off by default** and remembered in the browser. Off: no Activity card and no Call card. On: both appear (Activity: tool chips and knowledge searches; Call: call id, direction, status, turns, tokens, LLM cost, median latency). Business-facing feedback stays visible either way: the transcript with its system notices ("Identity verified", "Escalated: policy required", "Persona switched to ..."), the outcome banner and **Live controls**.
5. **The agent speaks first in Talk mode.** When the voice pipeline is up, the caller hears the welcome (greeting + disclosure for inbound and internal agents; the opening for outbound agents) without saying anything, and the same text is the first agent message in the transcript. **The welcome is protected**: while it plays, caller speech (including the agent's own voice picked up by the microphone) neither interrupts it nor is answered; the call's first caller turn is the first speech after the welcome ends. This also guarantees the AI disclosure in the welcome is always heard in full. A safety timeout ends the protection if the welcome never finishes. Text chat already shows its greeting on start and does not change. (An earlier draft of this CP blamed a start-up race between the transport and the pipeline; a frame-level reproduction showed the greeting does reach the speech stage, so that criterion was withdrawn.)
6. **No API, data, prompt or seed change.** `GET /api/use-cases` is unchanged; grouping by agent happens in the browser.

# Affected specs

* [/ui/test-call.md](/ui/test-call.md) - layout, agent select and "Handles" line, Test script card, Talk | Type placement, Technical details, welcome in Talk mode; UI-24 and UI-25 reworded, UI-08 qualified, UI-31, UI-32 and UI-33 new.
* [/architecture/voice-pipeline.md](/architecture/voice-pipeline.md) - the welcome is spoken once and is protected from interruption; VO-07 and VO-08 new (automated).
* [/api/voice-protocol.md](/api/voice-protocol.md) - `ready` precedes the welcome audio and the caller need not speak first.
* [/architecture/call-modes.md](/architecture/call-modes.md) - the "who speaks first" row also holds for voice calls (spoken, not only recorded).
* [/ui/index.md](/ui/index.md), [/product/demo-script.md](/product/demo-script.md), [/product/use-cases.md](/product/use-cases.md) - wording that mentioned the gallery or the category heading.

# Acceptance criteria

* **UI-24** (changed) - agent select, "Handles" line and a Test script with one starting phrase per use case instead of the gallery.
* **UI-25** (reworded) - outbound call from the agent select.
* **UI-08** (qualified) - the tool chip appears in Activity, which is shown when Technical details is on.
* **UI-31** (new) - Talk | Type lives in the call card and is locked during a call.
* **UI-32** (new) - Technical details is off by default, hides Activity and Call, and is remembered.
* **UI-33** (new, by hand with a microphone) - Talk start: the welcome is heard and shown first, with no speech from the tester.
* **VO-07** (new, automated) - the welcome is spoken exactly once, after `ready`, with the right text per mode.
* **VO-08** (new, automated) - the welcome is not interrupted by caller speech or echo and caller turns heard during it are not answered; after it ends, interruption and replies work as before.
* **VO-01** stays as the by-hand end-to-end check (real audio).

# Tasks

1. Spec edits (done in this CP).
2. Voice, `apps/api/voiceai/voice/processors.py` - `BrainProcessor` marks the call as *welcoming* from the start of the welcome until the agent has finished speaking it (or a safety timeout elapses, scaled to the text length); while welcoming, the caller-started-speaking event does not interrupt and caller turns are dropped - covers VO-07, VO-08.
3. Tests, `apps/api/tests/test_voice_welcome.py` - frame-driven tests of `BrainProcessor` for VO-07 (one `ready`, then the welcome text exactly once, per mode) and VO-08 (no interruption and no reply during the welcome, normal behavior after it, timeout); no network.
4. Web, `apps/web/app/test-call/page.tsx` (and small components if the file gets too large) - remove the gallery, add the "Handles" line and the Test script card, move Talk | Type into the call card, add the Technical details switch (`localStorage` key `test-call-technical`, wrapped in try/catch) - covers UI-24, UI-25, UI-08, UI-31, UI-32.
5. Verify in the browser at 375, 1024 and 1440 px, light and dark; do a real Talk call with a microphone (UI-33, VO-01); add UI-31, UI-32 and UI-33 to `scripts/acceptance-baseline.txt`; run `npm run build`, `uv run pytest` and `python scripts/spec_check.py --ci --base origin/main`.
6. Close: specs to `status: stable`, this CP to `cp_state: implemented`, `specs/log.md` entry.

# Risks and rollout

* **Cause shown, not yet confirmed in your browser.** The echo mechanism was reproduced against a scratch server (speech synthesis on, the agent's audio fed back as microphone input). Whether your speakers and microphone trigger it is confirmed by a headset test: with a headset the welcome should already play. If the welcome is still silent after the fix, the next suspect is the browser audio context.
* **Talking over the welcome no longer interrupts it.** A tester who starts talking during the welcome is not answered; they speak after it ends. The welcome is short (about 10 s with the default persona) and carries the AI disclosure, so this is intended. The Live-controls interruption toggle still governs every later reply.
* **Echo during the rest of the call is not addressed.** With open speakers the agent can still hear itself later in the call; a headset avoids it.
* **Demo flow.** The demo script uses tool chips; presenters must switch Technical details on. The script is updated.
* **Identity details are off screen.** A tester playing a caller must open the demo data or the demo script for the member ID and date of birth. That is the product owner's decision: the screen carries only the starting phrase. `GET /api/use-cases` keeps returning `demo_callers`; the page just does not render them.

# Out of scope

* Switching between Talk and Type during a running call (a call is created as voice or text; switching starts a new call).
* The other items from the UX review: a three-step guided flow, plain-language renames of Inbound / Outbound / Internal, simplifying Live controls, a pre-call microphone check, a result summary card.
* Removing the use-case data or the `/api/use-cases` endpoint; renaming the demo company in the seed data.
