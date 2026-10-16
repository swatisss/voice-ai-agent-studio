---
type: Runbook
title: Phone runbook
description: Answer a real phone call with an agent - local setup with a Twilio number and a tunnel, a no-Twilio local check, the Cloud Run setup, and troubleshooting.
status: stable
tags: [build, runbook, telephony, twilio, local, gcp]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-16T00:00:00Z" }
---

Spec: [/architecture/telephony.md](/architecture/telephony.md), [/architecture/realtime-voice.md](/architecture/realtime-voice.md). Everything here uses synthetic data only.

# One command (recommended for demos)

Put these in `apps/api/.env` once: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` (your Twilio number, `+1…`), `OPENAI_API_KEY`, and optionally `DEMO_TRANSFER_TO` (a phone to hand the call to). Install `ngrok` (and run `ngrok config add-authtoken …` once) or `cloudflared`. Then:

```bash
python scripts/phone_demo.py
```

It starts the tunnel and the API, maps the number to the Insurance Claims Agent, points the Twilio number at the tunnel and prints the number to call; Ctrl+C restores everything. Spec: [/build/phone-demo.md](/build/phone-demo.md). The numbered steps below are what it automates, and the fallback if you want to do them yourself.

# No Twilio account: the simulator

```bash
python scripts/phone_demo.py --simulator
```

Needs only `OPENAI_API_KEY`. Open `http://localhost:9200`: the page is a phone. Dial the shown number and talk (the Insurance Claims Agent answers; the conversation appears on the platform's Calls page with the Phone badge). For an **outbound** call, pick an outbound agent and a target in the outbound panel, enter your own phone number and press **Call me**: the page rings, press Answer and the agent speaks first (try the Claims Follow-up Agent, target Priya Nair). Spec: [/build/twilio-simulator.md](/build/twilio-simulator.md). Later, with real Twilio, run without `--simulator`.

# 0. Try the realtime agent without any phone

1. Add `OPENAI_API_KEY` to `apps/api/.env` and start the stack (`python scripts/dev.py`).
2. Open Test call, choose **Insurance Claims Agent**, press Talk. A realtime agent needs no Deepgram key.
3. Say "I want to check on a claim", then verify as Maria Lopez (member 482913, born April 12, 1986) and ask about claim C-20931.

If this works the pipeline, tools and prompts are fine, and only the phone path remains.

# 1. Local phone test with Twilio

You need: a Twilio account (a trial is enough), one Twilio phone number with voice, your own mobile phone, and a tunnel tool (ngrok or cloudflared).

1. **Twilio.** In the Console buy a phone number (Phone Numbers → Buy a number, voice enabled). On a trial account also verify your own mobile number (Verified Caller IDs); a trial plays a short notice and asks you to press a key before it connects.
2. **Keys.** Copy the Account SID and Auth Token from the Console dashboard into `apps/api/.env`:
   ```
   TWILIO_ACCOUNT_SID=AC...
   TWILIO_AUTH_TOKEN=...
   OPENAI_API_KEY=...         # realtime agent; DEEPGRAM_API_KEY + an LLM key for cascade agents
   ```
3. **Tunnel.** Start the API (`cd apps/api && uv run voiceai serve`, or `python scripts/dev.py`), then in another terminal:
   ```bash
   ngrok http 8000                                   # or: cloudflared tunnel --url http://localhost:8000
   ```
   Copy the `https://…` URL it prints.
4. **Tell the app its public URL.** In `apps/api/.env` set `PUBLIC_BASE_URL=https://<your-tunnel-host>` (no trailing slash) and **restart the API**. It must be exactly the host Twilio will call, or signature checks fail.
5. **Map your number to an agent.**
   ```bash
   cd apps/api && uv run voiceai phone add +15551234567 --agent "Insurance Claims Agent"
   uv run voiceai phone list
   ```
6. **Point Twilio at the app.** Console → Phone Numbers → your number → Voice Configuration → *A call comes in* → Webhook, **HTTP POST**, URL `https://<your-tunnel-host>/api/telephony/twilio/voice`. Save.
7. **Call the number from your mobile.** The agent speaks the welcome, then you can run the same script as in step 0. Open the Calls page: the call shows a **Phone** badge, its transcript and tools; `GET /healthz` shows `providers.twilio: true`.
8. **IVR context.** Add `?ivr_menu=claims` to the webhook URL in Twilio, call again, and open the call: the context shows `ivr_menu: claims`.
9. **Transfer.** In the agent builder set *Transfer to* to your second phone number (E.164) and publish. Call, ask for a person: the agent speaks the hand-off message and your second phone rings.

Every time the tunnel restarts its URL changes (free ngrok and cloudflared quick tunnels): update `PUBLIC_BASE_URL`, restart the API and update the Twilio webhook.

# 2. Local check with no Twilio account

```bash
cd apps/api && uv run voiceai phone add +15550001111 --agent "Insurance Claims Agent"
uv run python ../../scripts/fake_twilio.py --base http://localhost:8000 --to +15550001111 --wav your-recording.wav --ivr menu=claims
```

Run it from `apps/api` so it uses the API's Python environment; `--wav` is optional (without it the caller plays a one second tone, which exercises the pipeline but says nothing the agent can answer). `fake_twilio.py` signs a webhook request with `TWILIO_AUTH_TOKEN` (set any value in `.env`, and `PUBLIC_BASE_URL=http://localhost:8000`), follows the returned TwiML to the stream URL, plays the WAV as mu-law `media` events, prints events and writes the agent's reply audio to a WAV file. It exercises the webhook, signature, token, stream, pipeline and call recording, but not the phone network, Twilio's trial prompt or real mu-law line noise.

# 3. Cloud Run (GCP)

1. Deploy as in [/build/runbook-gcp.md](/build/runbook-gcp.md). Cloud Run already has what phone calls need: timeout 3600 s, CPU always on, one instance kept warm, session affinity, public HTTPS.
2. Store the Twilio secrets: `printf '%s' "$TWILIO_AUTH_TOKEN" | gcloud secrets create TWILIO_AUTH_TOKEN --data-file=-` (and `TWILIO_ACCOUNT_SID`, `OPENAI_API_KEY` if not already there). The deploy script attaches them when they exist.
3. Set `PUBLIC_BASE_URL` to the service URL (or your custom domain) and redeploy: `PUBLIC_BASE_URL=https://voiceai-xxxx-uc.a.run.app PROJECT_ID=… ./infra/deploy-cloudrun.sh`.
4. Map the number on the deployed service (the API with the tenant header, or `uv run voiceai phone add` against the Cloud SQL database), then change the Twilio webhook to `https://<service-url>/api/telephony/twilio/voice`.
5. Check `curl https://<url>/healthz` shows `providers.twilio: true` and `providers.openai: true`, then call.

Use the same region as your Twilio edge and the provider (default `us-central1`). Concurrent phone calls share the single instance's CPU: load-test before a larger demo.

# 4. Putting an IVR in front

Your IVR transfers or forwards to the Twilio number (PSTN forward) or to a Twilio SIP domain/URI that routes to the number. To pass the caller's menu choice or account hints, append `ivr_*` query parameters to the webhook URL in Twilio (static) or send SIP headers `X-IVR-<Name>` (dynamic); the agent sees them as context and still verifies identity. Confirm in the first test which one your IVR vendor supports.

# Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| Twilio Debugger shows 11200 / 403 on the webhook | Signature mismatch: `PUBLIC_BASE_URL` differs from the URL in Twilio (http vs https, old tunnel host, trailing slash). Fix both to match, restart the API. |
| Caller hears "not in service" | Number not mapped (`voiceai phone list`), agent not published, or `TWILIO_AUTH_TOKEN` / provider key missing (`/healthz`). |
| Call connects, silence | The stream URL is unreachable from Twilio (tunnel down), or the provider key is missing (close code 4500 in the API log). |
| Trial message then hang-up | Trial accounts only call or receive from verified numbers; press a key when prompted. |
| Agent talks over you / echo | Use a handset or headset; the browser's echo cancellation is not there on the phone. |
| Hand-off does not ring | `transfer_to` empty or not E.164, `TWILIO_ACCOUNT_SID` missing, or a trial restriction on the destination; the call still ends with the hand-off message and the console shows the escalation. |
