---
type: Product Brief
title: Northgate Health use cases
description: The fourteen demo use cases of a UK health insurer - member help and support, health insurance sales, and claims and pre-authorisation - with agent, flow, tools, knowledge, escalation triggers and demo callers.
status: stable
tags: [product, use-cases, demo]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-12T00:00:00Z" }
---

All fourteen live in the business unit **Northgate Health · Member & Sales Services** (category *Member & Sales Services*). Three agents serve them ([/demo-data/northgate-health.md](/demo-data/northgate-health.md)); the front desk routes each caller to the right one from what they say, replacing the "choose a topic" menus of a traditional help-and-support site and phone line ([/architecture/supervisor-routing.md](/architecture/supervisor-routing.md)). Every use case is available in **voice** and **chat**. Data is synthetic ([/demo-data/northgate-members.md](/demo-data/northgate-members.md)).

Common rules: members verify with their membership number and date of birth before any personal detail; prospects (sales) are never asked to verify; agents answer facts only from tools or approved knowledge; bank and card details are never taken on a call (secure links instead); complaints, cancellations, bereavement, disputes, requests for a person and anyone who seems vulnerable go to a person with a groundwork packet ([/architecture/escalation.md](/architecture/escalation.md)); a caller describing an emergency is told to call 999.

# Customer Care (member help and support)

**1. Policy & Cover Questions** — who is covered, excess, outpatient limit, hospital list, add-ons, underwriting and renewal date. Flow: verify → `get_member_policies` → `get_policy_details`; general "how does it work" → `search_knowledge`. Treatment approval or a consultant → transfer to Claims & Pre-authorisation. Demo: Sarah Mitchell.

**2. Payments & Direct Debit** — monthly amount, next collection, missed payments and getting cover back, the collection day, bank details. Flow: verify → `get_payments` → missed: explain suspension and the pay-by date → `retry_missed_payment` or `send_secure_link` (`make_payment`); `change_collection_day`; new bank → `send_secure_link` (`change_bank_details`). Escalates: disputed charge or refund. Demo: David Okoro (missed £61.20), Emma Clarke (collection day 15th).

**3. Update My Details** — email, mobile, postal address, read back before saving (`update_contact_details`). Escalates: adding or removing a person, change of name. Demo: Emma Clarke.

**4. Documents & Membership Card** — membership certificate, policy guide, membership card, premium statement, cash plan table of benefits by email, text link or post (`list_documents`, `request_document`). Demo: Raj Patel.

**5. Book a Digital GP Appointment** — video or phone with a GP or advanced nurse practitioner, 6am–10pm weekdays, 8am–10pm weekends, for anyone on the health policy (`get_gp_slots`, `book_gp_appointment`); emergencies → 999. Demo: Sarah Mitchell for her daughter Isla; Lucy Evans (cash plan only: not included).

**6. Cash Plan Cover & Claims** — limits used and left (`get_cash_plan_benefits`), claim status (`get_cash_plan_claims`, `get_cash_plan_claim`), how to claim with a receipt. Demo: Lucy Evans (optical claim above the limit), Emma Clarke (receipt without the patient's name).

**7. Renewal, Cancellation, Complaints & Bereavement** — explains renewal and the 21-day cooling-off from knowledge; cancelling, complaints and bereavement always hand over with a summary. Demo: Tom Harris (inside cooling-off), Raj Patel (complaint).

# Health Cover Sales (new customers, non-advised)

**8. Get a Health Insurance Quote** — who to cover, names, dates of birth, smoking, postcode, start date → `create_quote` → three packages with monthly prices. Demo: Alex Morgan and partner Sam (Bristol).

**9. Choose & Customise Cover** — Essentials or Complete, outpatient limit, excess, hospital list, add-ons; `price_quote` after every change; facts, never a recommendation. Escalates: the caller asks for personal advice. Demo: Gareth Lewis (smoker, London).

**10. Underwriting & Join by Phone** — moratorium, full medical underwriting or switching insurer → `assess_underwriting` (risk score, exclusions, final price; referrals go to a person) → personal details read back → key facts and declaration with a clear yes to each → `create_policy` → policy and membership numbers, start date, documents and a secure Direct Debit link by email or text, 21-day cooling-off. Demo: Alex Morgan (declares asthma: exclusion read out).

# Claims & Pre-authorisation (members getting treatment)

**11. Get Treatment Approved (Pre-authorisation)** — condition, when symptoms started, GP and recommended treatment → `check_treatment_cover` (exclusions, moratorium, missed payment, Essentials diagnostics; Direct Access or open referral) → `find_specialists` → read back → `create_pre_authorisation` → code, what it covers, excess, forms; surgery stays pending until the procedure code arrives. Escalates: disputes, clinical decisions, distress about cancer. Demo: Sarah Mitchell (knee pain, Direct Access, Leeds), Raj Patel (back pain excluded), David Okoro (cover suspended).

**12. Find a Consultant or Hospital** — recognised specialists on the member's hospital list near their postcode, fee-assured first (`find_specialists`). Demo: Emma Clarke near Bristol.

**13. Claim & Pre-authorisation Status** — `get_pre_authorisation`, `get_member_claims`, `get_claim_status`. Demo: Emma Clarke (`PA-500955` pending, `CL-70588` processing).

**14. Excess, Shortfalls & Invoices** — why the member got a bill; excess once per person per year; shortfall above fee guidelines; disputes to a specialist. Demo: David Okoro (£60 shortfall), Sarah Mitchell (£100 excess).

# Dental (demo kit)

The Oakhaven Dental Assistant and its eleven use cases are installed into the same business unit by `python scripts/demo_kits.py dental`; the front desk then routes dental callers to it ([scripts/demo/DEMO-KITS.md]).

# Editing use cases

The fourteen above are seeded. Builders add, edit and delete use cases per agent in the agent builder's **Use cases** tab ([/ui/agent-builder.md](/ui/agent-builder.md)) and through `/api/use-cases` ([/api/rest-api.md](/api/rest-api.md)). Use cases describe what an agent handles; the [capability catalog](/architecture/capability-catalog.md) indexes them for routing, so a change reaches the supervisor after the re-index. They are not versioned with the agent.

# Planted learning gaps (Act 6 of the demo)

The Customer Care agent deliberately lacks (a) knowledge on **adding a newborn to a policy** and (b) a **pre-authorisation status lookup**. Seeded history shows these as recurring escalation clusters; fixing them demonstrates fleet learning ([/architecture/fleet-learning.md](/architecture/fleet-learning.md)).

# Acceptance

- **~~UC-02~~** — Retired by CP-0039: the eight Evergreen use cases are replaced by the fourteen Northgate use cases (UC-11). Was: `GET /api/use-cases` returned eight use cases in category "Customer Support & Channels".
- **UC-07** — Given a builder who adds a use case "Lost ID card" with two sample utterances to the Customer Care agent, then `GET /api/use-cases` lists it under that agent, Test call's Handles line and Test script show it, and deleting it removes it from all three.
- **UC-11** — Given the seeded business unit, when `GET /api/use-cases` is called, then it returns the fourteen use cases in the order above, all with category "Member & Sales Services", seven linked to Customer Care, three to Health Cover Sales and four to Claims & Pre-authorisation, each linked to a published agent and each with at least three sample utterances.
