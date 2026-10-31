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
   > "If this is a medical emergency, please hang up and call 911. If you are thinking about harming yourself, you can call or text 988 at any time. I'm connecting you with a nurse right now."
7. **Appeals and grievances go to humans.** Filing an appeal or grievance is always escalated with category `policy_required`.
8. **Approved fixes only.** Drafted knowledge, tools, skills or rules affect callers only after a named human approves them; the nightly learning run only proposes ([/architecture/self-learning.md](/architecture/self-learning.md)).
9. **Caller ID identifies, it never verifies.** A call from a registered number is addressed by first name only; member data, the profile and memory need the date of birth (or member ID and date of birth). Three failed attempts go to a human; changes to contact or identity details always go to a human ([/architecture/caller-verification.md](/architecture/caller-verification.md)).
10. **Memory without health details.** Member memory never holds clinical details, payment details or identifiers, is read only after verification, expires automatically and can be erased per member at any time ([/architecture/agent-memory.md](/architecture/agent-memory.md)).

# Production gaps (not in v1)

* Business Associate Agreements with every processor (LLM, STT, TTS, cloud).
* PHI redaction before transcripts reach analytics, clustering or LLM drafting.
* Audit logging and access controls (roles: who may erase or export member memory); retention and deletion policies beyond member memory.
* Recording consent handling per jurisdiction.
* Call scoring sends production transcripts to the judge model and shows them to reviewers ([/architecture/call-scoring.md](/architecture/call-scoring.md)); in production the judge provider needs the same BAA coverage as the call, and review access needs roles and audit logging.
