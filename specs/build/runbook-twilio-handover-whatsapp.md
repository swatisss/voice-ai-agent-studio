---
type: Runbook
title: Twilio handover and WhatsApp runbook
description: What the owner does in the Twilio console and in apps/api/.env to get a phone call from India answered by the AI and handed warm to a person in India, and WhatsApp (sandbox first) with human handover, plus the demo script and the first-session spikes.
status: stable
tags: [build, runbook, telephony, twilio, whatsapp, handover, india]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-16T00:00:00Z" }
---

Spec: [/architecture/phone-warm-handover.md](/architecture/phone-warm-handover.md), [/architecture/whatsapp-channel.md](/architecture/whatsapp-channel.md), [/architecture/telephony.md](/architecture/telephony.md). Nothing here is live until [CP-0051](/changes/cp-0051-twilio-phone-warm-handover.md) and [CP-0052](/changes/cp-0052-whatsapp-via-twilio.md) are accepted and implemented. Synthetic data only: use made-up members from the Northgate Health demo. Twilio console menu names change; the names below are from Twilio's docs of 2026-11-16 and may differ slightly on screen. Facts are sourced in `.scratch/human-voice-and-channels/research/03-twilio-handover-whatsapp.md`.

# Before you start: decisions and costs

* A **paid Twilio account with a budget** (a trial only reaches verified numbers, plays a press-a-key prompt and limits calls to 10 minutes, so it cannot demo an unattended inbound call or a second Indian phone). Indicative prices from Twilio's India pricing page (note, fetched 2026-11-16): an outbound minute to an Indian mobile about $0.05, a browser or app leg $0.004, a US number from about $1.15 a month; your own call from India to the US number is billed by your Indian carrier at its international rate. Cap spending in the Console (usage triggers or a low balance).
* **Recording consent.** The plan records the human part of the call. Twilio warns that recording may need consent; the position in India is not verified. Keep `record` off until you have decided (the demo works without it, only the transcript step needs it).
* **Calling Indian mobiles from Twilio**: only from a non-Indian Twilio number, only your own staff or test phones, never members; commercial calls to people without their consent are treated as unsolicited under TRAI rules and may be blocked.

# A. Phone: AI answers, warm handover to a person in India

1. **Upgrade the account.** Console: add a payment method and fund it (Billing). Copy the **Account SID** (`AC…`) and **Auth Token** from the Console home.
2. **Create an API key** (Account > API keys & tokens > Create API key, type Standard). Copy the **SID** (`SK…`) and the **secret** (shown once). The platform downloads recordings with it and signs browser tokens with it.
3. **Buy a US number** with Voice (Phone Numbers > Manage > Buy a number, country United States, capability Voice). Note it in E.164 (`+1…`).
4. **Allow calls to India.** Console: Voice > Settings > Geo permissions; tick **India** (and keep United States). Calls to India must come from a non-Indian number, which the US number is. (The exact path and whether India is already enabled are not verified.)
5. **Turn on dual-channel conference recordings.** Console: Voice > Settings > General (Voice Recording settings): enable **Dual-channel Recording for Conference**. Without it a conference recording is mono and the transcript cannot tell the caller from the specialist.
6. **Put the keys in `apps/api/.env`** (never commit it):
   ```
   TWILIO_ACCOUNT_SID=AC…
   TWILIO_AUTH_TOKEN=…
   TWILIO_API_KEY_SID=SK…
   TWILIO_API_KEY_SECRET=…
   TWILIO_FROM_NUMBER=+1…            # the US number: also the caller ID for the specialist leg
   DEEPGRAM_API_KEY=…                # also used to transcribe the human leg
   OPENAI_API_KEY=…
   HANDOVER_STT_PROVIDER=deepgram    # Sarvam only after its ADR
   ```
7. **Public URL and webhooks, with the existing script.** `python scripts/phone_demo.py` starts the tunnel and the API, maps the number to the agent you choose (`DEMO_AGENT`), points the number's voice webhook at `${PUBLIC_BASE_URL}/api/telephony/twilio/voice` and prints the number ([/build/phone-demo.md](/build/phone-demo.md)). To do it by hand follow [/build/runbook-phone.md](/build/runbook-phone.md) steps 3 to 6 (`PUBLIC_BASE_URL` must be exactly the URL Twilio calls). The handover callbacks need no console setting: the platform passes their URLs on each call.
8. **Map the number to the front desk:** `cd apps/api && uv run voiceai phone add +1… --front-desk` (or `--agent "Customer Care"`).
9. **Set the agent's handover** in the agent builder (Telephony): *Transfer to* the specialist's Indian mobile in E.164 (`+91…`), *Handover* `conference`, *Record* on or off, *Ring seconds* 30, optionally *Ring Ready specialists' browsers*. Publish.
10. **Specialist in the browser (optional).** Sign in as the specialist (Agent Desk), open the Agent console, switch on **Take calls in this browser**, allow the microphone, keep the tab open.
11. **Test.** From your Indian mobile dial the US number. Expect: the AI answers; ask for a person ("mujhe kisi insaan se baat karni hai" works on a bilingual agent); you hear the hand-off message and then silence or your hold audio; the specialist phone rings, says the brief and connects you; after you hang up the call in Calls shows "Specialist call" within about a minute (once the recording is transcribed).

If the first call fails, run the spikes below before changing anything.

# B. WhatsApp via Twilio (sandbox first)

1. Same account, keys and public URL as above. (No extra Twilio purchase for the sandbox.)
2. **Open the sandbox** (legacy Console page, not in the new Console): `https://www.twilio.com/console/sms/whatsapp/sandbox`. Note the shared number `+14155238886` and your **join code**.
3. **Set the sandbox webhooks** on that page: *When a Message Comes in* = `${PUBLIC_BASE_URL}/api/channels/twilio/whatsapp/inbound`, method **HTTP POST**; *Status callback URL* = `${PUBLIC_BASE_URL}/api/channels/twilio/whatsapp/status`. Save.
4. **Map the sandbox to an agent:** `uv run voiceai whatsapp add whatsapp:+14155238886 --front-desk --label sandbox` (sandbox mode is the default for that number).
5. **Join from your own WhatsApp:** send `join <your code>` to `+14155238886`. A join lasts **3 days**: rejoin before a demo. The sandbox sends one message per 3 seconds and only to joined people.
6. **Test:** message "What is my excess?", then "I want to speak to a human". Open the Agent console as the specialist, accept, reply. The reply arrives on WhatsApp. A reply after 24 hours cannot use a custom template in the sandbox, so keep the demo inside the window.
7. **Voice note:** send a short Hindi voice note ("mera claim kahan tak pahuncha?"); the agent answers in text.

## Later: a production WhatsApp sender

Needs (Twilio's self sign-up page, 2026-11-16): an upgraded account; a Meta Business Portfolio (Meta business verification can take several weeks and is needed to scale); a phone number that is **not already registered with WhatsApp** and meets WhatsApp's requirements (a Twilio number can be used; whether a US number is accepted for Indian customers is not verified); a display name that follows Meta's guidelines (a rejected name limits you to 250 business-initiated messages a day). Console: Messaging > Senders > WhatsApp senders > Create new sender > Continue with Facebook, then follow the pop-up. Then:

1. Create the follow-up template in the **Content Template Builder** and submit it for approval (suggested text: "Hello, this is {{1}} from Northgate Health following up on your chat. Please reply to this message to continue."). Put its Content SID in `TWILIO_WHATSAPP_FOLLOWUP_CONTENT_SID`.
2. Point the sender's webhooks at the two routes above, add it with `voiceai whatsapp add whatsapp:+… --front-desk --production`.
3. Decide opt-in wording, privacy notice and the retention period for the customer's WhatsApp address (`WHATSAPP_ADDRESS_RETENTION_DAYS`), and check Indian rules (TRAI, DPDP) with counsel: not verified here.

# C. Spikes for the first paid session

Each is a ten-minute check; write the result in the CP's "Findings" section before implementation relies on it.

| Spike | Check | If it fails |
|---|---|---|
| S1 | Dial the US number from an Indian mobile: it connects and the AI answers | Try another Indian carrier, ask Twilio support; consider a Twilio toll-free `+91 1800` number or an Indian carrier (a different CP) |
| S2 | Escalate: the stream gets `stop` and the caller lands in the conference | Use `<Connect action>` returning the conference TwiML (plan B in the spec) |
| S3 | Conference recording has 2 channels, caller on channel 1; the recording can be deleted through the API | Accept mono (every line labelled mixed) or use `dial` mode with `record: true` |
| S4 | The browser rings through `Calls.create` to `client:desk-…`; `register`, `incoming`, token lifetime | Use a `<Dial><Client>` TwiML route |
| S5 | The leg to the Indian mobile rings, shows the US caller ID, and costs as expected | Check geo permissions, caller ID and Twilio's India guidelines |
| S6 | WhatsApp status callback field names and the out-of-window error code | Adjust the receipt parser |
| S7 | A voice note's content type and whether the media URL needs authentication | Adjust the downloader |
| S8 | A message from a WhatsApp user with a username (if you can test one) | Keep ignoring payloads without a phone number |
| S9 | Call and conference callback field names | Adjust the callback parsers |

# D. Demo script (about 8 minutes, synthetic member "Sarah Mitchell")

1. **Set up beforehand:** Section A and B done; the specialist signed in on a second device with *Take calls in this browser* on (or the specialist's Indian phone nearby); the sandbox joined within 3 days.
2. **Phone, Act 1.** The owner dials the US number from an Indian mobile. The AI states it is a virtual assistant and helps with an excess question after verification (membership number 410237, born 14 March 1984).
3. **Phone, Act 2.** The caller disputes a declined claim and asks for a person. The AI says it is connecting a colleague; the second phone (or the browser banner with the masked summary) rings; the specialist hears the spoken brief and answers; caller and specialist talk. Audience point: the AI is no longer on the line, the specialist was briefed, and the call is being recorded on two channels.
4. **Phone, Act 3.** Hang up. In Agent Desk the escalation shows; the specialist resolves with a note. About a minute later the call shows the **Specialist call** section with the caller's and the specialist's words (Hindi or English as spoken). Point to the Patterns page: the human portion is now evidence for a fix.
5. **WhatsApp.** On WhatsApp, message the sandbox number: "What is my excess?" then "I want to speak to a human". The Agent console shows a WhatsApp conversation with the reply-window countdown; the specialist replies; it arrives on WhatsApp with Delivered and Read ticks. Send a Hindi voice note; it is answered in text. Explain the 24-hour window and the template for late replies (the sandbox cannot send one; production can).
6. **Close.** Calls shows the phone call and the WhatsApp conversation side by side; both feed the same learning loop.
