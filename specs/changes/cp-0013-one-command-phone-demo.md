---
type: Change Proposal
title: CP-0013 One-command phone demo
description: One script that, given Twilio and OpenAI values in apps/api/.env, starts a public tunnel and the API, maps the number to the Insurance Claims Agent, points the Twilio number at the tunnel and waits for a call.
status: stable
cp_state: implemented
tags: [tooling, telephony, demo]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-16T00:00:00Z" }
---

# Why

The [phone runbook](/build/runbook-phone.md) has about nine manual steps (tunnel, `PUBLIC_BASE_URL`, restart, number mapping, Twilio console, and again every time the tunnel URL changes). For a live demo the presenter needs to fill in `.env` once and then run one command.

# What changes

`scripts/phone_demo.py`: reads `apps/api/.env`, starts a tunnel (ngrok if installed, else cloudflared), starts the API with `PUBLIC_BASE_URL` set to the tunnel URL, maps the Twilio number to the Insurance Claims Agent (optionally setting its transfer number), sets the number's voice webhook through the Twilio REST API, prints the number to call and shows calls as they happen. On Ctrl+C it restores the number's previous webhook and stops everything. Details: [/build/phone-demo.md](/build/phone-demo.md).

# Affected specs

* [/build/phone-demo.md](/build/phone-demo.md) - new, DEV-07…DEV-11.
* [/build/runbook-phone.md](/build/runbook-phone.md) - leads with the one-command path; the manual steps stay as the fallback.
* [/build/index.md](/build/index.md), [/changes/index.md](/changes/index.md), [/build/runbook-local.md](/build/runbook-local.md) - pointers.

# Acceptance criteria

DEV-07…DEV-11 in [/build/phone-demo.md](/build/phone-demo.md).

# Tasks

1. Spec edits (done first).
2. `scripts/phone_demo.py` — covers DEV-07…DEV-11.
3. `apps/api/tests/test_phone_demo.py`; `.env.example` gets `TWILIO_PHONE_NUMBER`, `DEMO_*`.

# Risks and rollout

* Needs `ngrok` (with an auth token) or `cloudflared` on the machine; the script says which is missing and how to install it. Free tunnels change URL on every start, which is why the script re-points Twilio each time.
* It changes the Twilio number's webhook while it runs and restores the previous value on exit; a killed script (not Ctrl+C) leaves the new webhook until the next run.
* Verified here only against local fakes of the tunnel, the Twilio REST API and the app API (no Twilio account or tunnel in this session); DEV-11 is a by-hand check.

# Out of scope

Buying or releasing numbers, creating Twilio accounts, Cloud Run deployment (see the runbook), outbound dialing.
