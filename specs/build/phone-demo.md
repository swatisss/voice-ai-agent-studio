---
type: Tool Spec
title: Phone demo launcher
description: scripts/phone_demo.py - from values in apps/api/.env to a working phone number in one command - tunnel, API, number mapping, Twilio webhook, live call feed and clean restore.
status: stable
tags: [build, tooling, telephony, demo]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-16T00:00:00Z" }
---

# Usage

Fill in `apps/api/.env` once, then:

```bash
python scripts/phone_demo.py             # tunnel + API + number mapping + Twilio webhook, then call the number
python scripts/phone_demo.py --check     # pre-flight only: what is configured, what is missing; starts nothing
```

Windows without a `python` command: `py -3 scripts/phone_demo.py`. Stdlib only (Python 3.9+); it starts the API with `uv`.

| `.env` key | Required | Meaning |
|---|---|---|
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | yes | Your Twilio credentials (used for webhook validation, the transfer and to set the number's webhook) |
| `TWILIO_PHONE_NUMBER` | yes | The Twilio number to answer, international format, e.g. `+15551234567` |
| `OPENAI_API_KEY` | yes, for the default agent | The Insurance Claims Agent runs on the realtime pipeline |
| `NGROK_AUTHTOKEN` | no | Needed by ngrok itself; the script passes it through |
| `DEMO_AGENT` | no | Agent to answer the number (default `Insurance Claims Agent`) |
| `DEMO_TRANSFER_TO` | no | A phone number (or `sip:` URI) the call is redirected to on a hand-off; set on the agent and published when it differs |

| Flag | Meaning |
|---|---|
| `--port N` | API port (default 8000) |
| `--public-url URL` | Use this public URL instead of starting a tunnel (a Cloud Run URL, your own tunnel) |
| `--keep-webhook` | Do not restore the number's previous webhook on exit |
| `--check` | Pre-flight only |

# What it does, in order

1. **Pre-flight.** Reads `apps/api/.env` and the environment. Missing required keys, no tunnel tool (neither `ngrok` nor `cloudflared`; unless `--public-url`), no `uv`, or a busy port are reported with the fix, and nothing starts. A `PUBLIC_BASE_URL` left in `.env` is ignored: the script owns it.
2. **Tunnel.** `ngrok http <port>` when installed (the public URL is read from ngrok's local API), otherwise `cloudflared tunnel --url http://127.0.0.1:<port>` (the URL is read from its output).
3. **API.** `uv run voiceai serve --port <port>` in `apps/api` with `PUBLIC_BASE_URL` set to the public URL; waits until `/healthz` answers.
4. **Mapping.** Through the API: finds the agent by name, maps `TWILIO_PHONE_NUMBER` to it (re-mapping if it pointed at another agent), and when `DEMO_TRANSFER_TO` is set makes it the agent's transfer number and publishes. Running again changes nothing that is already right.
5. **Twilio.** Finds the number in the account with the REST API and sets its voice webhook to `<public URL>/api/telephony/twilio/voice` (POST), remembering the previous value.
6. **Ready.** Prints the number to call, the public URL and what to expect (a Twilio trial plays a notice and only accepts verified callers), then prints each call as it starts and ends, with its outcome.
7. **Ctrl+C.** Restores the number's previous webhook (unless `--keep-webhook`) and stops the API and the tunnel.

# Acceptance

- **DEV-07** — Given a `.env` without `TWILIO_AUTH_TOKEN` and `OPENAI_API_KEY`, or with a `TWILIO_PHONE_NUMBER` that is not in international format, or with neither `ngrok` nor `cloudflared` on the path, when pre-flight runs, then each problem is reported with its fix and no value of a key is printed; with everything present it reports none, and `--check` starts no process and makes no network call.
- **DEV-08** — Given ngrok's tunnel listing, then the `https` public URL is picked; given a cloudflared output line, then its `trycloudflare.com` URL is picked; given `--public-url`, then no tunnel is started; a `PUBLIC_BASE_URL` in `.env` is ignored and the API receives the tunnel's URL.
- **DEV-09** — Given a Twilio account that owns the number, when the webhook step runs, then the number's voice URL becomes `<public URL>/api/telephony/twilio/voice` with method POST and the previous voice URL is returned for restoring; given a number the account does not own, then the step fails with a message naming the number; restoring puts the previous URL back.
- **DEV-10** — Given the API with the seeded agents, when the mapping step runs, then the number is mapped to the named agent; run again it changes nothing; run with the number mapped to another agent it is re-mapped; with a transfer number set it is saved on the agent and published once, and not again when already equal; an unknown agent name fails naming the agent.
- **DEV-11** — Given real Twilio and OpenAI credentials, a tunnel tool and a phone, when `python scripts/phone_demo.py` runs and the number is called, then the agent answers and the call appears in the printed feed and on the Calls page; Ctrl+C restores the webhook and leaves no process running (by hand).
