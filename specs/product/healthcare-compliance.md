---
type: Compliance Note
title: Healthcare compliance rules
description: Safety, privacy, verification and disclosure rules every healthcare agent on the platform must follow, and the production gaps v1 leaves open.
status: draft
tags: [product, healthcare, compliance, safety]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Rules enforced in v1

1. **Synthetic data only.** No real member data, PHI or PII may be loaded into v1 environments.
2. **Disclosure.** Every call opens with the persona's disclosure: the caller is talking to a virtual assistant and the call may be recorded for quality.
3. **Identity before PHI.** Tools that return member-specific data are marked `requires_verification`. The runtime MUST block them until a verification tool has returned `verified: true` in the same call ([/architecture/tools-and-skills.md](/architecture/tools-and-skills.md)). General plan information (how deductibles work, how to add a newborn) needs no verification.
4. **Minimum necessary.** The agent discloses only what answers the question; it never reads back full member IDs, full dates of birth or other members' data.
5. **No medical advice.** The agent never diagnoses, recommends treatment or interprets symptoms. It offers the 24/7 nurse line or escalates.
6. **Safety screen.** Before any LLM call, each caller utterance is checked for emergency or self-harm language. On a match the agent responds with the fixed safety message and escalates with category `safety` ([/architecture/escalation.md](/architecture/escalation.md)). Safety message:
   > "If this is a medical emergency, please hang up and call 911. If you are thinking about harming yourself, you can call or text 988 at any time. I'm connecting you with a nurse right now."
7. **Appeals and grievances go to humans.** Filing an appeal or grievance is always escalated with category `policy_required`.
8. **Approved fixes only.** Drafted knowledge or skills affect callers only after a human approves them.
9. **The camera is the caller's, and camera media transits a third party.** The camera is off until the caller turns it on, and neither the agent nor the API can enable it ([/architecture/visual-intake.md](/architecture/visual-intake.md), VI-02). Be plain about what follows: **while the camera is on, video streams continuously to LiveKit Cloud's SFU and into the service**, because the transport offers no way to request a single frame ([ADR-0009](/decisions/adr-0009-video-channel.md)). All but the latest frame is dropped on arrival, and **no frame is encoded, stored or shown to a model unless the agent called `look_at_camera`** (VI-03). The agent says out loud that it looked and the caller sees the evidence entry appear ([/ui/visual-case.md](/ui/visual-case.md)). A deployment that cannot accept third-party media transit must leave LiveKit unconfigured, which turns video calls into voice calls (VI-01).
   This is weaker than the rest of this document and deliberately recorded as such. A production deployment would need a BAA with the media provider, the same as with the LLM, STT and TTS providers.
10. **The agent does not over-claim what it saw.** An observation carries a confidence the model is required to withhold when the frame does not support the caller's description, and a withheld confidence is recorded rather than discarded. The agent asks for a better look instead of guessing, and it never reports `not_confirmed` as an accusation. In this domain a case that falls apart at review is the failure that matters, and this is the rule that prevents it.
11. **No evidence is generated.** No role or tool in the product produces an image of what a caller is reporting, so nothing can manufacture the evidence the product exists to check ([/architecture/imagery.md](/architecture/imagery.md), IMG-01). The one rendered image is the agent's own avatar face (rule 13), which is never stored, pinned or shown to a model. Demo imagery is synthetic, checked in, and labelled as a sample wherever it appears.
13. **The face is an AI agent, never a real person.** On a video call the agent may appear as a stock face rendered by the avatar service ([/architecture/avatar.md](/architecture/avatar.md)). It is labelled **AI agent** wherever it is shown, in addition to the spoken disclosure of rule 2, and it is never a real person's likeness: faces are chosen from the vendor's stock set, and creating one from an uploaded photograph is out of scope. The avatar service receives the agent's synthesised speech, which can contain member information read back to the caller; a deployment that cannot accept that leaves `SIMLI_API_KEY` unset and gets a video call with no face.
12. **Captured frames expire; the finding does not.** Stored frames are deleted after the retention window (30 days by default) while the description, confidence and the caller's words remain, so a case stays auditable after its images are gone ([ADR-0010](/decisions/adr-0010-media-retention.md)). Media we store is readable only through one authorised, tenant-checked endpoint — there is no public or signed URL (MS-05). Room access is scoped the same way: a call's token admits its bearer to `call-<call_id>` and to no other room, in this tenant or any other ([/api/media-protocol.md](/api/media-protocol.md), VI-13). What LiveKit Cloud itself retains of the transiting media is the provider's to state, not ours, and is a question a production deployment must answer before it carries real patients.

14. **On the Live engine, the caller's speech goes to Google, and the camera does not.** A video call on the Gemini Live engine streams the caller's microphone to a Gemini Live session on Vertex AI for the whole call, and the agent's face and voice come back from it ([/architecture/live-session.md](/architecture/live-session.md), [ADR-0012](/decisions/adr-0012-gemini-live-avatar.md)). That replaces Deepgram for these calls rather than adding to it. The camera is stricter than on the LiveKit engine (rule 9): nothing streams to anyone; the browser sends one still only when the agent calls `look_at_camera`, to our server, and it goes to the `vision` role like any other (GL-11, VI-03). **The wording of the safety message (rule 6) is recorded and shown exactly but is spoken by a model that is instructed to say it, so the audio is not guaranteed verbatim** (GL-08). The face is labelled **AI agent** as in rule 13. A deployment that cannot send call audio to Google leaves `VIDEO_ENGINE` on `livekit` or the Vertex settings unset.

# Production gaps (not in v1)

* A Business Associate Agreement with Google for Vertex AI, before the Live engine carries real patients' speech.

* Business Associate Agreements with every processor (LLM, STT, TTS, cloud).
* PHI redaction before transcripts reach analytics, clustering or LLM drafting.
* Audit logging and access controls. v1 has a media retention window but **no audit trail of who viewed a frame** and no deletion-on-request path, so a caller cannot ask for their image to be removed ahead of the window.
* Recording consent handling per jurisdiction, including **visual** capture, which several jurisdictions treat differently from audio. v1's disclosure says the call may be recorded; it does not obtain a separate consent for images, nor for camera media transiting a media provider.
* A BAA with the avatar vendor. The agent's speech, which can include member details, is sent to it to be rendered.
* Review of captured frames for incidental PHI. A caller pointing a camera at a ward can capture a person, a chart or a screen that nobody asked for, and v1 neither detects nor redacts it.
