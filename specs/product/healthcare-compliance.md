---
type: Compliance Note
title: Healthcare compliance rules
description: Safety, privacy, verification and disclosure rules every healthcare agent on the platform must follow, and the production gaps v1 leaves open.
status: stable
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
   > "If this is a medical emergency, please hang up and call 999. If you are thinking about harming yourself, you can call Samaritans free on 116 123 at any time. I'm connecting you with a nurse right now."

   The screen matches English phrases and Hindi phrases (Devanagari and Latin letters) on every agent; when the triggering turn is in Devanagari the Hindi safety message is spoken instead ([/architecture/languages.md](/architecture/languages.md)). Hindi safety message (to be approved by a clinical or compliance reviewer before real callers hear it):
   > "अगर यह मेडिकल इमरजेंसी है, तो कृपया फ़ोन रखें और 999 पर कॉल करें। अगर आप खुद को नुकसान पहुँचाने के बारे में सोच रहे हैं, तो आप कभी भी Samaritans को 116 123 पर मुफ़्त कॉल कर सकते हैं। अब आपको एक नर्स से जोड़ा जा रहा है।"
7. **Appeals and grievances go to humans.** Filing an appeal or grievance is always escalated with category `policy_required`.
8. **Approved fixes only.** Drafted knowledge, tools, skills or rules affect callers only after a named human approves them; the nightly learning run only proposes ([/architecture/self-learning.md](/architecture/self-learning.md)).
9. **Caller ID identifies, it never verifies.** A call from a registered number is addressed by first name only; member data, the profile and memory need the date of birth (or member ID and date of birth). Three failed attempts go to a human; changes to contact or identity details always go to a human ([/architecture/caller-verification.md](/architecture/caller-verification.md)).
10. **Memory without health details.** Member memory never holds clinical details, payment details or identifiers, is read only after verification, expires automatically and can be erased per member at any time ([/architecture/agent-memory.md](/architecture/agent-memory.md)).

11. **No PHI to processors without a BAA in routing.** With `PHI_MODE` on (the default on Cloud Run) the supervisor never sends caller text to a hosted decision model; the embedding, which runs inside the platform, decides instead ([/architecture/supervisor-routing.md](/architecture/supervisor-routing.md)). Webhooks carry IDs only unless a tenant asks for transcripts, and never carry member identifiers or phone numbers ([/architecture/webhooks.md](/architecture/webhooks.md)).

12. **Only an admin changes what callers hear.** Reviewers work escalations, answers and reviews; publishing an agent and approving a learning fix need the admin role, and every version records who published it ([/architecture/studio-auth.md](/architecture/studio-auth.md)).

13. **Messages only through the contact tools, minimum necessary.** Email, SMS and message calls go to a verified member's registered contact (read from the business API at sending time, never stored, shown masked) or to an address the caller gives and confirms after a read-back; a new address is never saved to the record. A message never carries the member ID; at most three per call; simulations and evaluations never deliver ([/architecture/contact-tools.md](/architecture/contact-tools.md)).

How each rule is enforced and which tests prove it: [Compliance evidence](/product/compliance-evidence.md).

# Production gaps (not in v1)

* Business Associate Agreements with every processor (LLM, STT, TTS, cloud).
* PHI redaction before transcripts reach analytics, clustering or LLM drafting.
* Audit-log export and an identity provider (v1 has two fixed demo accounts; only the admin may erase member memory); retention and deletion policies beyond member memory.
* Recording consent handling per jurisdiction.
* Call scoring sends production transcripts to the judge model and shows them to reviewers ([/architecture/call-scoring.md](/architecture/call-scoring.md)); in production the judge provider needs the same BAA coverage as the call, and review access needs roles and audit logging.
* Email and SMS are not end-to-end encrypted, and Brevo and Twilio receive message text and recipient addresses: production needs agreements with them, per-number sending limits and possibly portal links instead of details in messages.
* Webhook URLs are not checked against private networks (SSRF), and API keys are managed by anyone with Studio access; both need roles and network controls in production. A TURN relay for WebRTC processes call audio and needs BAA coverage.
