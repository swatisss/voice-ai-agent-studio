# Dental agent demo: from "a human had to step in" to "the agent answers" (about 10 minutes)

The story: a ready-made dental front-desk agent handles bookings, prices, insurance and emergencies. A caller asks about something nobody taught it (home visits for a housebound parent), so it hands the call to a person. You paste one paragraph of knowledge, publish, ask again, and it answers. Then the same agent by voice.

Oakhaven Dental Care is fictional; every patient and record is synthetic. Files: `scripts/demo/dental/` (`knowledge/` holds the three files the agent starts with, `paste-home-visits.md` is the text you paste on stage).

---

## Before the audience arrives (5 minutes)

1. Terminal 1, the stack (leave it running):
   ```
   python scripts/dev.py
   ```
   If replies time out on this network: `python scripts/stack.py start --llm openai:gpt-4.1-mini` instead.
2. Terminal 2, build the agent (about 2 seconds), and **leave it running**: it serves the practice's booking and insurance system that the tools call:
   ```
   python scripts/demo_kits.py dental --tenant evergreen-care
   ```
   Expect `5 passed, 0 failed` and `agent published: Oakhaven Dental Assistant v1 … voice: realtime`, then `Serving the mock patient system … Press Ctrl+C to stop`.
3. Open **http://localhost:3000** in Chrome, sign in as the admin if asked; business unit **Evergreen Health · Customer Support & Channels**.
4. Open `scripts/demo/dental/paste-home-visits.md` in an editor, ready to copy.
5. Headset plugged in; allow the microphone for localhost when Chrome asks.
6. **Rehearse once, then reset**: run the step 2 command again (Ctrl+C the old one first). It puts the agent back to its three files and publishes a new version, so the home-visits gap is back.

---

## Act 1: Meet the agent (2 minutes)

**Agents → Oakhaven Dental Assistant → Open.**

| Tab | Show | Say |
|---|---|---|
| **Use cases** | 11: booking, moving or cancelling, emergencies, prices, cover and estimates, claims, Care Plans, aftercare, practice info, sedation, complaints | "What this agent handles, in plain words. The front desk also uses this to route callers here." |
| **Persona** | Maya: greeting and the AI disclosure | |
| **Policy** | Rules, Never (diagnose, recommend medicine, promise insurance pays), Escalate when | "Plain-English guardrails; every call is scored against them." |
| **Knowledge (3)** | Three Oakhaven documents, ticked. Other rows belong to other agents and stay unticked | "Everything it may say comes from approved knowledge." |
| **Tools (11)** / **Skills (5)** | `dental_*` tools: verify, register, slots, book, move, cancel, cover, estimate, claim status, claim documents | "Connected to the practice's booking and insurance systems." |
| **Voice** | **Realtime speech-to-speech** | |

## Act 2: A question it cannot answer (2 minutes)

**Test call** → **Single agent** → *Oakhaven Dental Assistant*, **Technical details** on, **Type**, **Start chat**.

| Caller types | Expect |
|---|---|
| "How much is a check-up?" | `search_knowledge`: £55 (a warm-up it gets right) |
| "My mum is 84 and housebound. Can a dentist come to her home?" | `search_knowledge` finds nothing about home visits; Maya says she doesn't have that information and offers to connect you with the team |
| "Yes, please." | `escalate_to_human`; Maya hands over ("I'm passing you to our patient care team…"); the chat ends as escalated |

Then **Console** (left navigation): the escalation is waiting, with the groundwork packet: the question, what the agent searched and why it handed over.

Say: "It didn't guess. No approved answer, so a person takes over with the full context. Now let's teach it."

## Act 3: Teach it in one paste (1 minute)

Back to **Agents → Oakhaven Dental Assistant → Knowledge**.

| Do | Expect | Say |
|---|---|---|
| **Paste text**. Title `Home visits`; content: everything in `paste-home-visits.md` → **Add** | A new row *Home visits*, ticked; tab shows **Knowledge (4)** | "One paragraph from the practice manager." |
| **Test search**: `home visits for housebound patients` → **Search** | *Home visits › Home visits for housebound patients* on top | "It is searchable straight away." |
| **Save draft**, then **Publish**, change note `Home visits` | Badge **v2** | "Callers only ever get a published version." |

## Act 4: Ask again (1 minute)

**Test call** → **Start new call** (a new chat uses the new version), **Type**:

| Caller types | Expect |
|---|---|
| "My mum is 84 and housebound. Can a dentist come to her home?" | Yes: a dentist and dental nurse visit homes and care homes within 10 miles of a practice, on Tuesday and Friday afternoons |
| "How much does that cost, and how do I book?" | £120 plus treatment; call the nearest practice; a family member can book; usually within two weeks |
| "Thanks, bye!" | Goodbye; **Was this helpful?** |

Say: "Same question, two minutes later, answered from the paragraph we just added, with no code and no retraining."

## Act 5: The same agent by voice (2 minutes)

**Talk** → **Start call**, speak into the headset after Maya's greeting:

| Say | Expect |
|---|---|
| "Hi, can a dentist visit my mother at home? She's housebound." | The home-visits answer, spoken |
| "I knocked my front tooth out playing football. What should I do?" | Hold it by the crown, keep it in milk, come within an hour; offers the £85 emergency appointment |
| "Are you open on Saturdays?" | Manchester and Bristol 9am to 1pm; Leeds closed |
| "That's everything, thanks." | Goodbye; **Hang up** |

Speak in short sentences and pause; Maya waits for you to finish.

## Optional: tools and identity (2 minutes, text)

| Caller types | Expect |
|---|---|
| "I'd like to book a hygiene appointment in Leeds." → "OD-10231, born 12 April 1988." → "The first one." → "Yes." | Verifies Priya, offers slots, reads the booking back, books it: a BK- reference and the 48-hour cancellation rule |
| "How much would a crown cost me with my insurance?" | £795; her insurance pays nothing until 1 July 2027 (12-month waiting period) |
| As Tom, **OD-10457**, born **30 September 1975**: "What's happening with claim DC-5560?" | Needs the itemised receipt |

---

## If something goes wrong

| Symptom | Fix |
|---|---|
| Act 2 already answers about home visits | The pasted text from a rehearsal is still attached: rerun the build command (it resets to the three files) |
| Act 4 still escalates | Not published, or the chat was started before publishing: **Publish**, then **Start new call** |
| Booking, cover or claim tools fail ("connection error") | Terminal 2 is not running: run the build command again |
| "Request timed out" in replies | Restart with `python scripts/stack.py start --llm openai:gpt-4.1-mini` |
| Voice stutters | **Voice** tab must say **Realtime speech-to-speech**; use a headset |
| Use **Single agent**, not **Full flow** | Full flow starts at the front-desk router, which needs another model |
