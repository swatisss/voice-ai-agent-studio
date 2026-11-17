---
type: Runbook
title: LiveKit runbook
description: What the owner does to try a live voice handover - create a free LiveKit Cloud project, set three secrets, run the connectivity check, then a two-machine demo on localhost and on Cloud Run.
status: stable
tags: [build, runbook, livekit, voice, handover, gcp]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-16T00:00:00Z" }
---

Spec: [/architecture/hosted-media-room.md](/architecture/hosted-media-room.md), [/decisions/adr-0015-hosted-media-room-livekit.md](/decisions/adr-0015-hosted-media-room-livekit.md). Synthetic data only. Nothing here is needed for the other transports.

# 1. Create the LiveKit Cloud project (about 5 minutes, free)

1. Sign up at LiveKit Cloud (the Build plan needs no credit card; check the sign-up page says so on the day).
2. Create a project. Name it anything, for example `echo-mind-demo`. Pick the region nearest the Cloud Run region (`us-central1` by default, so a US region).
3. Open the project's **Settings** and find the **API keys** section (the exact menu label was not verifiable; look for "Keys"). Create a key pair, name it `echo-mind`.
4. Copy three values and keep them out of chat and git:
   * the project **WebSocket URL**, looks like `wss://<project>.livekit.cloud`
   * the **API key** (starts `API`)
   * the **API secret** (shown once)
5. Leave everything else default. You do not need agents, SIP, egress, webhooks or a storage bucket for the first cut.
6. Note the plan limits on the project's usage page: 5,000 participant-minutes and hard caps. Calls stop when they run out; nothing is billed on the free plan.

# 2. Set the environment

Local, in `apps/api/.env` (the file is ignored by git; names only here):

```
LIVEKIT_URL=wss://<project>.livekit.cloud
LIVEKIT_API_KEY=<your key>
LIVEKIT_API_SECRET=<your secret>
```

Optional: `LIVEKIT_TOKEN_TTL_S` (default 600), `HANDOVER_WAIT_S` (default 180).

Cloud Run: put the key and secret in Secret Manager and pass them like the other secrets (`LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` as secrets, `LIVEKIT_URL` as an env var); `infra/deploy-cloudrun.sh` treats all three as optional. Keep `--min-instances 1 --max-instances 1 --no-cpu-throttling` ([/architecture/deployment.md](/architecture/deployment.md)): the AI and the scribe are live clients of the room, not requests.

# 3. Check connectivity first (this decides the design)

```bash
python scripts/livekit_check.py        # from your machine
```

It joins a throw-away room and prints signalling OK or failed, the media path (UDP, TCP or relay) and the round-trip time. Then run the same check **from Cloud Run** (a one-off Cloud Run job running the same image and command; the implementation CP adds the exact line to [/build/runbook-gcp.md](/build/runbook-gcp.md)). Results:

| Result | Meaning | Do |
|---|---|---|
| UDP, round trip under 300 ms | Best case | Continue |
| TCP or relay | Works, slightly slower | Continue; note the latency |
| Signalling OK, media failed | Cloud Run cannot send UDP and the SDK does not fall back | Tell the agent; the fallback is a separate always-on worker (VM) or Daily ([ADR-0015](/decisions/adr-0015-hosted-media-room-livekit.md)) |
| Signalling failed | Wrong URL or key | Re-copy the three values |

# 4. Two-machine demo

* Customer: open `/test-call/?agent=<id>` on machine A (Chrome, microphone allowed), switch **Voice connection** to **Voice room** and press **Start call**. Use a headset.
* Specialist: on machine B sign in as `specialist@echomind.test` (Agent Desk), open the console. Use a headset, allow the microphone.
* Say "I want to speak to a person" on machine A. The AI hands off; the console card shows **Live voice - waiting**; press **Take the call** on machine B. The AI says one line and leaves; talk. Press **Resolve** with a note: the call ends and the transcript shows both voices.
* Open **Escalated calls** to see the transcript with the specialist's lines marked as human, and **Patterns** to see them as evidence.

# 5. Troubleshooting

| Symptom | Check |
|---|---|
| Start returns 503 `livekit_unavailable` | The three settings are missing; `/healthz` shows `livekit: false` |
| "Voice is unavailable" in the page | The AI could not join (limits reached, wrong URL, media blocked); run the check |
| Customer hears nothing from the specialist | Specialist microphone permission; headset; browser autoplay (click once on the page) |
| Echo | Use headsets on both machines |
| Specialist lines missing from the transcript | Speech provider key (`DEEPGRAM_API_KEY`) is needed for the scribe |
| Calls stop at about 5,000 minutes | Free plan cap reached; see the project usage page |
