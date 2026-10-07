---
type: Product Brief
title: Customer Support & Channels use cases
description: The seven demo use cases for a health insurer - agent, mode, channels, flow, tools, knowledge, escalation triggers and demo callers for each.
status: stable
tags: [product, use-cases, demo]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-06T00:00:00Z" }
---

All seven live in the business unit **Evergreen Health · Customer Support & Channels** (category shown in the UI: *Customer Support & Channels*). Four agents serve them ([/demo-data/evergreen-health.md](/demo-data/evergreen-health.md)). Every use case is available in **voice** (browser microphone) and **chat**. Data is synthetic ([/demo-data/members-and-claims.md](/demo-data/members-and-claims.md)). Tool names are the platform tools of [/demo-data/evergreen-health.md](/demo-data/evergreen-health.md).

Common rules: identity is verified (member ID + date of birth) before any policy, claim or document detail; the agent answers facts only from tools or approved knowledge; appeals, grievances, safety language and requests for a person escalate with a groundwork packet ([/architecture/escalation.md](/architecture/escalation.md)).

# 1. Policy Inquiry & Status

* **Agent / mode**: Customer Care, inbound.
* **Goal**: tell the policyholder what policies they hold, whether each is active, when it renews, what they pay and whether payments are up to date.
* **Flow**: verify → `get_member_policies` → (if a specific policy) `get_policy_details` → explain status, cover period, premium, next payment, renewal date; explain grace periods from knowledge when a payment is overdue.
* **Knowledge**: policy types and statuses, premiums and payments.
* **Escalates when**: the caller wants to cancel, change cover mid-term or dispute a charge.
* **Success**: resolved without a human; sample: "Is my policy still active and when does it renew?"
* **Demo caller**: Maria Lopez (health, renews in 25 days); Robert Chen (payment overdue, in grace period).

# 2. Claims Status Tracking

* **Agent / mode**: Customer Care, inbound.
* **Goal**: give status, amounts, expected decision date and the timeline of a claim.
* **Flow**: verify → claim number (or `get_member_claims` to find it) → `get_claim_status` → status, what the plan paid, member share, timeline and next step.
* **Knowledge**: claim statuses and timelines, appeals and grievances.
* **Escalates when**: the claim is denied and the caller disputes it or wants to appeal (policy: `policy_required`).
* **Demo callers**: Maria Lopez, claim C-20931 (paid), C-20977 (processing); James Carter, C-31544 (denied, appeal → escalation with packet).

# 3. Document Center & Green Card

* **Agent / mode**: Customer Care, inbound.
* **Goal**: send policy documents (policy schedule, policy wording, membership card, premium invoice, tax certificate, certificate of insurance) and issue the **Green Card** - the international motor insurance certificate that proves motor cover when driving abroad.
* **Flow**: verify → `list_documents` for the policy → confirm delivery (email, download link, post) → `request_document`; for a Green Card also collect destination countries and travel dates (motor policies only, up to 90 days, email or download).
* **Knowledge**: document center, Green Card rules and covered countries, membership cards.
* **Escalates when**: the destination is not covered, the policy is not active, or the caller needs a document the center does not offer.
* **Demo callers**: James Carter (motor policy MP-200415 → Green Card for Spain); Maria Lopez asks for a Green Card but has no motor policy (explained, no document issued); Daniel Kim (policy schedule by email).

# 4. Outbound Renewal Calls

* **Agent / mode**: Renewal Outreach, **outbound**: the agent calls the policyholder.
* **Goal**: remind about the upcoming renewal, explain the price change, offer options and record the decision (accept, decline, callback).
* **Flow**: agent opens with the persona's outbound opening ("Hello, may I speak with <first name>? … calling about your renewal") → confirms the person and verifies date of birth (no detail before this) → `get_renewal_quote` → explains the premium change and reasons → presents options → `record_renewal_decision`.
* **Knowledge**: renewal process, price changes explained, payment options and discounts, changing or cancelling cover.
* **Escalates when**: the callee is upset, asks for a person, wants to cancel for a complaint, or asks for advice the agent cannot give.
* **Targets**: policyholders whose policy renews within 60 days, from the renewal outreach list (nearest first). **Demo targets**: James Carter (motor, +8%, 13 days), Maria Lopez (health, +4%, 25 days).

# 5. Policyholder Onboarding

* **Agent / mode**: Welcome & Onboarding, **outbound** welcome call to new policyholders.
* **Goal**: complete the onboarding checklist: confirm contact details, communication preferences, online account registration, membership card download, choose a primary provider, review waiting periods.
* **Flow**: opening → verify date of birth → `get_onboarding_status` → walk through pending steps, `complete_onboarding_step` as each is done, `request_document` to send the membership card → summarize what is left.
* **Knowledge**: welcome guide, digital account setup, using your membership card, first 30 days (waiting periods).
* **Escalates when**: the member reports an error in their policy or cannot be verified.
* **Targets**: members with open onboarding steps. **Demo targets**: Aisha Okafor (5 steps left), Daniel Kim (3 left).

# 6. Internal Knowledge Assistant

* **Agent / mode**: Internal Knowledge Assistant, **internal** (audience: Evergreen staff, assumed authenticated by the surrounding channel).
* **Goal**: answer procedure and policy questions for claims handlers and agents: claims handling steps, authorization limits, complaints and escalation matrix, fraud indicators, data-protection rules, call-handling standards.
* **Flow**: `search_knowledge` first, answer with the article title as the source; `get_authorization_limit` for approval limits; `get_escalation_contact` for who to contact.
* **Rules**: never discloses member data; says when the procedure is not documented; no member verification.
* **Escalates when**: the question is not covered by internal knowledge twice (`knowledge_gap`).
* **Sample questions**: "What can a claims handler approve for inpatient?", "Who do I contact about a suspected fraud?"

# 7. Coverage Information Support

* **Agent / mode**: Customer Care, inbound.
* **Goal**: explain what the plan covers: benefits, limits and what is left, waiting periods, pre-authorization, co-pay, exclusions, deductible and out-of-pocket status, in-network providers.
* **Flow**: general question → `search_knowledge`; own plan → verify → `get_coverage_detail` (benefit, limit, used, remaining, waiting period, pre-authorization) and `get_benefits` (deductible, out-of-pocket, copays); `find_providers` for network questions.
* **Knowledge**: coverage benefits overview, waiting periods and exclusions, deductibles and out-of-pocket maximums, copays by plan, finding providers, prior authorization, nurse line.
* **Escalates when**: coverage for a specific treatment is ambiguous or needs a clinical decision; never gives medical advice.
* **Demo callers**: Priya Nair (dental limit and waiting period), Daniel Kim (specialist copay and deductible).

# Planted learning gaps (Act 3 of the demo)

The Customer Care agent deliberately lacks (a) knowledge on **adding a newborn to a policy** and (b) a **prior-authorization status lookup**. Seeded history shows these as recurring escalation clusters; fixing them demonstrates fleet learning ([/architecture/fleet-learning.md](/architecture/fleet-learning.md)).

# Acceptance

- **UC-02** — Given the seeded business unit, when `GET /api/use-cases` is called, then it returns the seven use cases in the order above, all with category "Customer Support & Channels", each linked to an existing published agent, and each with at least two sample utterances.
