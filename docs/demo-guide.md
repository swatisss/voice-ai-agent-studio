# Echo Mind Voice Agent Studio — End-to-end demo

October 31, 2026

## What this demo shows

In about 35 minutes the audience watches one story: you build a new voice agent without code, talk to it, see every call scored, test it against scenarios, and watch the platform propose its own improvements — which only a human can publish.

| Act | What you show | Time |
| --- | --- | --- |
| 1. Tour | Dashboard, business units, the sidebar | 2 min |
| 2. Build | A new *Prior Authorization Assistant*: persona, rules, a knowledge article, a new tool, a skill, memory, scoring settings, publish | 8 min |
| 3. Playground | Text and voice test calls: verification, a tool lookup, a knowledge answer, memory, feedback | 6 min |
| 4. Call detail | Transcript, tool calls and the call's scorecard; a human review of one verdict | 3 min |
| 5. Hand-off | An escalation with a groundwork packet in the Agent console | 3 min |
| 6. Measure | The Evaluation page: scores per version, drift, judge calibration; a test suite run | 6 min |
| 7. Learn | Run learning now, the learning inbox, the check, approve and publish | 7 min |

The agent you build in Act 2 is new, so it has no history yet. Acts 6 and 7 therefore also use the seeded **Customer Care Agent**, which comes with four weeks of calls, ready-made problem clusters and test scenarios.

## Before you start

Do these the evening before, then again 30 minutes before you present.

- [ ] **Keys in `apps/api/.env`:** an LLM key (`GROQ_API_KEY`, `OPENAI_API_KEY` or `OPENROUTER_API_KEY`) and `DEEPGRAM_API_KEY` for voice. Without Deepgram, use the **Type** tab everywhere; every act still works.
- [ ] **Fresh demo data:** `cd apps/api && uv run voiceai seed --reset`. This gives four weeks of history (123 calls), five agents, the problem clusters and the test scenarios.
- [ ] **Start the stack:** `python scripts/dev.py` from the repo root. Web at http://localhost:3000, API at http://localhost:8000. Use `localhost`, not an IP, or the browser blocks the microphone.
- [ ] **Pick the business unit:** bottom of the sidebar → *Customer Support & Channels*.
- [ ] **Speed up the learning check:** open the Customer Care Agent → **Evaluation** tab → *Learning* card → set *Test repeats when checking a proposal* to **1** → **Save draft** → **Publish**. A proposal check then needs about 30 simulated calls instead of about 70.
- [ ] **Pre-run the learning loop:** Dashboard → **Run learning now**, and wait until the card shows the run (several minutes with real models). This plays the "overnight" run, so the inbox is full when you reach Act 7.
- [ ] **Headset** for voice, to avoid echo.
- [ ] **Windows to have open:** the app in one window, and the **Agent console** in a second window for a teammate playing the human specialist (Act 5).

**Demo callers** (they share these details only when the agent asks):

| Caller | Member ID | Date of birth | Useful for |
| --- | --- | --- | --- |
| Maria Lopez | 482913 | April 12, 1986 | Policy status, claim C-20931 (paid) |
| James Carter | 337120 | November 2, 1979 | Denied claim C-31544, Green Card |
| Priya Nair | 559804 | July 23, 1992 | Prior authorization PA-77812 (approved) |
| Aisha Okafor | 725031 | September 15, 1990 | Prior authorization PA-77930 (pending review) |
| Robert Chen | 610277 | January 30, 1958 | Prior authorization PA-78001 (denied) |
| Daniel Kim | 801456 | March 8, 2001 | Documents by email |

## Act 1 — Tour (2 min)

Open with the **Dashboard**: one place shows how every agent of this business unit is doing.

1. Point at the four tiles: **Calls** (123), **Containment rate** (about 68%), **Escalated to human**, **Response time**.
2. Show **Containment by week** and **Escalations by root cause**: most hand-offs come from a few missing answers and missing lookups.
3. Show **Top clusters**: *Adding a newborn to coverage* and *Prior authorization status* are marked **Ready for fix**.
4. Scroll to the **Self-learning** card: "Runs every night at 02:00 UTC", last night's numbers, and proposals waiting for review. Say you will come back to it.
5. Walk the sidebar in one sentence each:
    - **Agents** — build and version agents.
    - **Personas** — reusable voices and speaking styles.
    - **Test call** — the playground.
    - **Calls** — every conversation, with its scorecard.
    - **Agent console** — where humans take over.
    - **Insights** — what goes wrong, and proposed fixes.
    - **Evaluation** — scores and test suites.
    - **Settings** — voice pipelines and keys.
6. Show the **Business unit** switcher at the bottom of the sidebar: every agent, call and score belongs to one unit and never leaks into another.

**Say:** "Agents here are declarative. You describe what the agent knows, what it may do and what it must never do. The platform runs it, scores it and learns from it."

## Act 2 — Build a new agent (8 min)

You build a **Prior Authorization Assistant** in front of the audience: it answers "what is a prior authorization" from a knowledge article and looks up a member's authorization through a new tool.

**Create it**

1. **Agents** → **New agent**. Name: `Prior Authorization Assistant`. Description: `Answers prior authorization questions and checks the status of a member's authorization.` → **Create**. The builder opens on the new draft.
2. **Overview** tab: leave *Call mode* on **Inbound**. Show the *Realtime model* select: any agent can switch model with one choice.

**Give it a voice and rules**

3. **Persona** tab: pick a library persona (for example *Ava*), or edit the inline fields: name, voice, greeting, disclosure, speaking style. The disclosure ("I'm a virtual assistant…") is required.
4. **Policy** tab, add one line each:
    - *Rules*: `Verify identity with member ID and date of birth before sharing any member-specific information.`
    - *Escalate when*: `The caller wants to appeal a denied prior authorization.`
    - *Never*: `Give medical advice or say whether a treatment is needed.`

**Teach it**

5. **Knowledge** tab → **Paste text**. Title: `Prior authorization basics`. Content (Markdown):

```markdown
# Prior authorization basics
A prior authorization is the plan's approval, before some services, that the service is covered. Your doctor's office requests it, not you.
## How long it takes
Standard requests are decided within 5 business days. Urgent requests are decided within 72 hours.
## If it is denied
Your doctor can resubmit with more records. You can also ask a specialist to start an appeal.
```

Save it, tick it as attached, and open the preview to show the chunks. Run **Test search** with `how long does a prior authorization take` to show the scored result.

**Give it hands**

6. **Tools** tab: tick the existing **verify_member** tool. Then **New tool**:

| Field | Value |
| --- | --- |
| Name (snake_case) | `get_prior_auth_status` |
| Method | GET |
| Description | `Status of one prior authorization of the verified member, by number like PA-77930.` |
| URL | `/mock/healthcare/prior-auths/{auth_id}` |
| Parameters (JSON Schema) | `{"type":"object","properties":{"auth_id":{"type":"string","description":"Authorization number like PA-77930"}},"required":["auth_id"]}` |
| Requires verification | on |

Save and tick it. Say: "Requires verification means the platform blocks this lookup until the caller is verified, whatever the model tries."

7. **Skills** tab → **New skill**:
    - *Name*: `Prior authorization status`
    - *Use when*: `The caller asks whether an authorization was approved, is pending, or was denied.`
    - *Steps*: `1. Verify identity. 2. Ask for the authorization number. 3. Look it up and explain the status and what happens next in one or two sentences.`
    - *Required tools*: `verify_member`, `get_prior_auth_status`
    - *Escalate when*: `The caller wants to appeal a denial.`

**Memory and scoring**

8. **Memory** tab: leave *Remember callers between calls* on. Point at *Never remember…* and the note that health and payment details are never stored, whatever you write.
9. **Save draft**, then open the **Evaluation** tab. Show *Checks this agent is scored on*: your *Never* line now appears as a **Hard gate** check marked *From your policy*, and your escalation lines as checks too. Add one **Custom check**: `Did the agent say when to expect a decision for a pending authorization?` (group *Outcome*). Show the *Learning* card: nightly learning on, proposals always wait for review.
10. **Publish** → change note `First version` → **Publish**. The header shows **v1**.

**Say:** "No code. Knowledge, tools, rules and how it is scored are all settings, and publishing freezes them into a version every call will record."

## Act 3 — Try it in the playground (6 min)

Open **Test call**, pick **Prior Authorization Assistant** in the agent select, and switch **Technical details** on (top right) so the audience sees each tool call, knowledge search and cost.

**Call 1 — a recognised caller, in Type mode**

1. Set **Call from** to *Priya Nair — registered number*, keep **Type**, press **Start chat**. The agent greets her by first name and asks only for her date of birth: a registered number identifies a caller but never verifies them.
2. Type: `Hi, is my MRI authorization PA-77812 approved? And please send me updates by text, that's easiest for me.`
3. When asked, type: `July 23rd, 1992.` Watch **Activity**: `verify_member` ✓, then `get_prior_auth_status` ✓. The agent says it was approved and is valid through December 20.
4. Type: `What happens if one gets denied?` Activity shows a knowledge search hitting *Prior authorization basics*; the answer comes from your article (resubmit with records, or appeal through a specialist).
5. Type: `Great, that's all, thanks.` The call ends by itself, the banner says **Resolved**, and **Was this helpful?** appears. Click **Yes**.

**Call 2 — the same caller by voice, with memory**

6. Wait about 10 seconds (the agent writes its memory of call 1 in the background). Switch to **Talk**, keep *Priya Nair — registered number*, press **Start call**. The agent speaks first: greeting and disclosure.
7. Say your date of birth when asked, then: `How long does a pending authorization usually take?` The agent answers from the article (5 business days, 72 hours if urgent) and can use what it remembered, such as her preference for text messages.
8. While it talks, open **Live controls** and switch the **Persona** (for example to *Grace*): the next reply uses the new voice and style. Flip **Turn detection** to *Semantic* and dictate a number slowly: the agent waits instead of cutting in.
9. Say `Bye` to end. Answer **No** to the feedback prompt and type `Too slow` to show the comment box.

**Optional — the verification gate:** start a new chat with *Call from: No number* and type `What's the status of PA-77930?` before giving any details. The agent asks for member ID and date of birth first. Even if the model tried the lookup, the platform blocks member data until verification succeeds (Aisha Okafor: `725031`, September 15, 1990; the authorization is pending clinical review).

**Say:** "Same brain on every channel: chat, browser voice, phone, and speech-to-speech. Verification, tools and memory behave the same everywhere."

## Act 4 — See what happened (3 min)

Every call is recorded, analysed and scored within seconds of ending. Open **Calls** and click call 1 (newest first; filter by agent if needed).

1. **Header:** outcome, channel, version **v1**, duration, cost and "Identified by caller ID".
2. **Transcript:** each tool call is an expandable row with its arguments and result; the knowledge search shows the article and score.
3. **Memory** card: what the agent knew at verification and what it updated after the call, each with its reason. **Member memory** opens everything this agent remembers about Priya, with the source call of each item, restore, erase and export.
4. **Caller feedback** card: the Yes or No and the comment.
5. **Scorecard** card ("Not scored yet" turns into the card without a reload):
    - the score and measures: first response, p50 and p95 response time, tool calls and errors, knowledge searches;
    - checks grouped by Outcome, Responsiveness, Knowledge, Tools, Memory and Safety, each with a verdict, a *Code* or *Judge* tag and a reason;
    - your *Never* rule and your custom check are there, scored on this call;
    - click a **Turn n** evidence link: the transcript scrolls to that line and highlights it.
6. On any *Judge* check click **Disagree**, pick the correct verdict, add a note and save. Your verdict shows next to the judge's. Say: "These reviews are how we learn whether to trust the judge."
7. **Analysis** card: intent, root cause, the caller's goal and sentiment, used later to find patterns across calls.

**Say:** "Safety checks such as 'no member data before verification' are decided from the event log in code, not by an LLM's opinion. The judge only answers the questions code cannot."

## Act 5 — Hand-off to a human (3 min)

When the agent should not handle something, it hands the call over with notes, so the caller never repeats themselves. Keep the **Agent console** open in the second window.

1. On **Test call**, with the Prior Authorization Assistant, *Call from: No number*, **Start chat**.
2. Type: `My CPAP authorization PA-78001 was denied and I want to appeal it.`
3. Give `610277` and `January 30, 1958` when asked. The agent looks the authorization up (denied: insufficient documentation, the provider may resubmit with a sleep study), explains it, and — because your *Escalate when* rule says so — hands over: "I'm connecting you with a specialist…". The banner reads **Escalated — waiting for a specialist**.
4. In the console window the escalation appears at once under **Waiting** with a chime. Within a second or two the **groundwork packet** fills in: summary, intent, authorization number as a chip, *Already tried* (identity verified, authorization looked up), reason, sentiment from start to end, and a suggested next action.
5. The teammate clicks **Accept**, reads the packet aloud, chooses disposition *Appeal filed*, writes a note (`Started an appeal; asked the provider for the sleep study.`) and clicks **Resolve**.

**Say:** "That resolution note is the ground truth of what a human told the caller. When enough calls go the same way, the platform drafts a fix from those notes — that's Act 7."

The call's detail page now shows the escalation, the packet, the disposition and the note next to its scorecard.

## Act 6 — Measure it (6 min)

Two questions: how is each agent doing with real callers (**Scorecards**), and will a change still handle the situations that matter (**Test suites**)?

**Scorecards — the seeded Customer Care Agent**

1. **Evaluation** → agent *Customer Care Agent*, period *Last 90 days*, *Include seeded history* on.
2. Tiles for the published version: Goal met, Containment, Grounded, Hard fails, p95 response time, Helpful. The **Grounded** tile carries a **Drift** badge: "Lower than in this version's first week".
3. **Trend**: goal met, containment and grounded per day, hard fails as bars.
4. **Checks**: every check with its pass rate. Judge checks show reviews, agreement and **Uncalibrated** until 20 human reviews agree at least 85% of the time; only calibrated checks will ever count as learning signals.
5. Click the **Grounded** row: the call list filters to the 5 calls that failed it. Open one to show the judge's reason.
6. Switch the agent to **Prior Authorization Assistant**: your calls from Acts 3 to 5 are already here, scored against v1.

**Test suites — your new agent**

7. Click the **Test suites** tab. The new agent has no scenarios yet. **New scenario**:
    - *Name*: `Pending knee surgery authorization`
    - *Caller's goal*: `You want to know whether your knee surgery authorization PA-77930 has been decided.`
    - *Persona*: **Adversarial** (tries to get information before verifying, gets the date of birth wrong once)
    - *Expected outcome*: Resolved
    - *Caller*: `Aisha Okafor`, member ID `725031`, date of birth `1990-09-15`
    - *Required tools*: `get_prior_auth_status` with argument `auth_id` = `PA-77930`
    - **Save scenario**
8. **Run suite**: target *Published v1*, *Repeats* `3` → **Run suite**. The button counts "Running 2 of 3" as simulated callers play the scenario.
9. In **Runs**, open the run: a grid of scenario × run with ✓ or ✕. Click a cell for its failure reasons (for example "get_prior_auth_status was never called with auth_id=PA-77930") and **Open the simulated call** — it has a **Simulated** badge and its own scorecard.
10. Say why three runs: "A scenario counts as passing only if it passes every time. One lucky run hides a flaky agent."
11. Optional: back in the builder, change the draft (for example add a *Never* line), press **Run tests** in the header: the suite runs against the unpublished draft and reports "… scenarios passed every run", without blocking **Publish**. Every publish also runs the suite automatically, so each version has a baseline.

On the Customer Care Agent's Test suites tab, show its eight seeded scenarios, including *Wrong date of birth first* (adversarial) and *Remembers email preference* (stand-in memory).

## Act 7 — Watch it learn (7 min)

Every night the platform reviews each agent's calls, drafts fixes and checks them. Nothing reaches callers until a person approves. You pre-ran the "night" during setup, so the results are waiting.

1. **Dashboard** → **Self-learning** card: when the last run finished, calls reviewed, signals found, proposals drafted and how many passed the check, and **N waiting for review**.
2. Press **Run learning now** to show the trigger. The button reads **Learning…** and the card updates when it finishes. Clusters that already have a proposal are skipped, so this second run is quick.
3. Click **Review proposals** → **Insights**. At the top: the **Last night** strip and **Waiting for review** — one card per proposal with a *Nightly* badge, its kind, title, rationale and a **Passed** or **Failed** badge.
4. Open *Adding a newborn to your coverage* (**Open**). Show:
    - **Evidence**: 14 escalated calls, each with what the human specialist actually told the caller.
    - **Proposed fix**: a knowledge article written from those notes (60-day window, member portal steps, birth record). The drafter never adds member data or medical advice.
    - **Derived test scenarios**: built from real calls, added to the test suite on approval.
    - **Evaluation**: the current version against the fix on the cluster's calls, on calls **held out** from the drafter, on the derived scenarios and on the whole test suite. Summary such as "Baseline 0/6 → Candidate 5/6 · Held out 3/4 · No regressions", and **Check passed**.
5. Click any cell of the grid: each run's result, its failures and the simulated call.
6. **Approve & publish**. A banner confirms the new version, "From fix: …". Publishing starts a test run of the new version automatically.
7. **Live proof:** **Test call** → *Customer Care Agent* → Type: `Hi, I just had a baby last week. How do I add her to my plan?` The agent now answers from the new article instead of handing over.
8. Open the second proposal, *Prior authorization status*, and **Reject** it with a note (`We'll add the lookup ourselves`). Say: "Rejected problems are left alone for seven days, so the same idea is not proposed every night."

If a proposal's check **failed**, its reasons are listed (for example "1 test scenario regressed: Claim paid 3/3 → 1/3"). **Approve** is disabled; **Publish anyway** asks for a written reason.

**Say:** "It learns only from real signals — escalations, unhappy callers, unanswered searches, failed lookups, and judge verdicts that humans have confirmed. It proposes; people decide."

## Optional extras

Pick these by audience; each takes 1–3 minutes.

| Extra | How | What it shows |
| --- | --- | --- |
| Speech-to-speech voice | **Test call** → *Insurance Claims Agent* → Talk. Needs `OPENAI_API_KEY`, no Deepgram. **Settings** must allow realtime (it does in the seed). | One OpenAI model listens and speaks: lower delay. Same tools, verification and scoring as the cascade agents. |
| Outbound call | **Test call** → *Renewal Outreach Agent* → *Who should the agent call?* → James Carter → **Place outbound call**. | The agent speaks first, verifies the date of birth before any price, explains the renewal and records the decision. |
| Onboarding call | *Welcome & Onboarding Agent* → Aisha Okafor → **Place outbound call**. | Walks a checklist and records each step. |
| Staff assistant | *Internal Knowledge Assistant* → Type: `What can a claims handler approve for inpatient?` | Internal mode: answers staff from internal articles, refuses member data. |
| A real phone call | `python scripts/phone_demo.py` with Twilio values in `.env`, then call the number. | Inbound phone calls on a published agent, transfer to a human number on hand-off. |
| Personas | **Personas** page: create one (voice, speed, greeting, style) and **Try** it. | One voice shared by several agents; switch persona mid-call. |
| Settings | **Settings**: allow realtime, and save the unit's own OpenAI key (stored encrypted, shown only as the last 4 characters). | Per-business-unit control of voice pipelines and keys. |
| Member memory | Open a verified call → **Member memory** → **Erase member** or **Export**. | Memory is visible, explainable and erasable per member. |

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Talk closes at once with "Voice is unavailable" | `DEEPGRAM_API_KEY` is missing. Use **Type**; every act works the same. |
| Microphone blocked | Open the app on `http://localhost`, not an IP address. |
| The agent interrupts itself | Use a headset; the microphone is picking up the speaker. |
| Replies slow or failing, Groq 429 in the API log | Groq's free tier is rate-limited. Add `OPENAI_API_KEY` (every role falls back to it) or switch roles to OpenAI in `.env` (see the local runbook). |
| Scorecard stays "Not scored yet" | Scoring runs after the call's analysis in the background job worker; give it 5–20 seconds. `python scripts/dev.py` runs the worker; check the `[api]` log for LLM errors. |
| Memory not used in call 2 | The caller must be verified in both calls, and the first call needs a few seconds after it ends to be remembered. |
| Run learning now takes minutes | Expected with real models: each proposal is checked with dozens of simulated calls. Lower *Test repeats when checking a proposal* to 1, and pre-run it before presenting. |
| The card shows "N drafts failed" | The drafting model returned something unusable. Check the API log, then **Run learning now** again. |
| Wrong agents or empty dashboard | Check the business unit at the bottom of the sidebar; reseed with `uv run voiceai seed --reset`. |

The nightly run fires only when 02:00 UTC passes while the server is running. Starting the server never launches it, so nothing runs during your demo unless you press the button.

## Feature checklist

| Area | Feature | Shown in |
| --- | --- | --- |
| Build | No-code agent builder: overview, persona, policy, voice, memory, knowledge, tools, skills, evaluation, versions | Act 2 |
| Build | Knowledge from pasted text, uploaded files (.md, .txt, .pdf, OKF zip) or a URL; test search | Act 2 |
| Build | HTTP tools with JSON-schema parameters and a verification gate | Act 2 |
| Build | Skills: plain-English procedures with required tools and escalation rules | Act 2 |
| Build | Immutable versions; every call records its version | Acts 2, 4 |
| Build | Persona library, inbound, outbound and internal modes | Act 2, extras |
| Run | Playground in Type and Talk, Technical details, test script | Act 3 |
| Run | Live persona and turn-detection switching mid-call | Act 3 |
| Run | Caller identification by registered number, verification by date of birth | Act 3 |
| Run | Member memory across calls, visible and erasable | Acts 3, 4, extras |
| Run | Cascade voice (Deepgram) and realtime speech-to-speech (OpenAI) | Act 3, extras |
| Run | Phone calls through Twilio, transfer on hand-off | Extras |
| Run | Caller feedback after each call | Act 3 |
| Hand-off | Escalation with a groundwork packet, agent console, dispositions and notes | Act 5 |
| Measure | Scorecard on every call: measures, code and judge checks, hard gates, evidence | Act 4 |
| Measure | Human review of judge verdicts and judge calibration | Acts 4, 6 |
| Measure | Evaluation page: per-version rollups, trend, drift, checks, scored calls | Act 6 |
| Measure | Test suites: personas, expected tools and results, stand-in memory, repeated runs, pass^k | Act 6 |
| Measure | Run tests on a draft; automatic test run on publish | Act 6 |
| Learn | Call analysis, clustering, impact and readiness | Acts 1, 7 |
| Learn | Nightly self-learning at 02:00 UTC and Run learning now | Act 7 |
| Learn | Proposal kinds: new article, article edit, tool attach, skill, rule | Act 7 |
| Learn | The check: held-out calls, derived scenarios, test suite on both versions, no slowdown | Act 7 |
| Learn | Learning inbox, approve and publish, publish anyway with a reason, reject and snooze | Act 7 |
| Operate | Business units with isolated data, Settings for pipelines and keys | Act 1, extras |
