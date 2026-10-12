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
9. **The camera is the caller's.** It is off until the caller turns it on, and neither the agent nor the API can enable it ([/architecture/visual-intake.md](/architecture/visual-intake.md), VI-02). Nothing is captured or uploaded except the single frame a `look_at_camera` asked for, the agent says out loud that it looked, and the caller sees the capture happen ([/ui/visual-case.md](/ui/visual-case.md)).
10. **The agent does not over-claim what it saw.** An observation carries a confidence the model is required to withhold when the frame does not support the caller's description, and a withheld confidence is recorded rather than discarded. The agent asks for a better look instead of guessing, and it never reports `not_confirmed` as an accusation. In this domain a case that falls apart at review is the failure that matters, and this is the rule that prevents it.
11. **No image is generated.** No adapter, role or tool in the product produces an image, so nothing can manufacture the evidence the product exists to check ([/architecture/imagery.md](/architecture/imagery.md), IMG-01). Demo imagery is synthetic, checked in, and labelled as a sample wherever it appears.
12. **Captured frames expire; the finding does not.** Stored frames are deleted after the retention window (30 days by default) while the description, confidence and the caller's words remain, so a case stays auditable after its images are gone ([ADR-0010](/decisions/adr-0010-media-retention.md)). Media is readable only through one authorised, tenant-checked endpoint — there is no public or signed URL (MS-05).

# Production gaps (not in v1)

* Business Associate Agreements with every processor (LLM, STT, TTS, cloud).
* PHI redaction before transcripts reach analytics, clustering or LLM drafting.
* Audit logging and access controls. v1 has a media retention window but **no audit trail of who viewed a frame** and no deletion-on-request path, so a caller cannot ask for their image to be removed ahead of the window.
* Recording consent handling per jurisdiction, including **visual** capture, which several jurisdictions treat differently from audio. v1's disclosure says the call may be recorded; it does not obtain a separate consent for images.
* Review of captured frames for incidental PHI. A caller pointing a camera at a ward can capture a person, a chart or a screen that nobody asked for, and v1 neither detects nor redacts it.
