---
type: Seed Data
title: Synthetic call history
description: Design of the ~120 historical calls seeded for the Customer Care agent of Northgate Health - volumes, intents, outcomes, clusters, analyses and human resolution notes.
status: stable
tags: [demo-data, seed, learning]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Window and generator

* Four weeks: the 28 days ending the day before seeding (for a seed on 2026-10-05 that is 2026-09-07 → 2026-10-04), business hours, deterministic RNG seed `42`. Dates are relative so a reseed before any demo keeps clusters inside the 28-day impact window.
* Channel `voice`, agent version v1, `is_seed: true`, analyses with `source: seed` (no LLM needed to seed).
* Each call gets a short transcript (4–10 events) from templates, consistent with [/demo-data/northgate-members.md](/demo-data/northgate-members.md); costs ≈ $0.004–0.012 (LLM cost, in dollars); latency 650–1,400 ms.
* Each call gets a scorecard with `source: seed` ([/architecture/call-scoring.md](/architecture/call-scoring.md)): measures and code checks computed from its events as for a real call; judge checks set without a model: `outcome.goal_met` fails for the 3 abandoned calls and passes otherwise, `outcome.escalation_appropriate` passes, `knowledge.grounded` fails for 5 resolved `coverage_question` calls (reason "Stated a coverage detail that no tool or knowledge result supports"; the latest one of weeks 2 and 3 and the latest three of week 4, so they fall in the last 7 days), passes for the other resolved calls and is `n/a` for escalated and abandoned ones; every other check passes or is `n/a`. No reviews are seeded.
* Agent replies that follow a caller line carry `latency_ms` within 650–1,400 ms (the call's latency ± up to 100 ms), so the measures have response times.

# Mix (123 calls)

| Intent | Count | Outcome | Root cause | `cluster_key` |
|---|---|---|---|---|
| `policy_status` | 14 | resolved | none | — |
| `payment_question` | 26 | resolved | none | — |
| `document_request` | 16 | resolved | none | — |
| `coverage_question` (half policy cover, half cash plan limits) | 20 | resolved | none | — |
| `gp_booking` | 6 | resolved | none | — |
| `add_dependent_newborn` | 14 | escalated (`knowledge_gap`) | `missing_knowledge` | `newborn` |
| `prior_auth_status` | 9 | escalated (`capability_gap`) | `missing_skill` | `prior_auth` |
| `complaint` | 8 | escalated (`policy_required`) | `policy_required` | `complaints` |
| `cancellation` | 3 | escalated (`policy_required`) | `policy_required` | `cancellation` |
| `speak_to_person` | 4 | escalated (`caller_requested`) | `caller_requested` | `caller_requested` |
| abandoned (mixed intents) | 3 | abandoned | other | — |

Weekly volume grows slightly (27, 30, 32, 34); newborn escalations are spread 3, 3, 4, 4 so the cluster is "recent and growing". Resulting containment ≈ 67%. Amounts are in pounds and dates are spoken the UK way ("14 March 1984").

# Clusters (created directly from `cluster_key`)

| key | name | description | fixable |
|---|---|---|---|
| `newborn` | Adding a newborn to the policy | Callers want to know how and when to add a new baby to their health insurance; no approved article exists. | yes |
| `prior_auth` | Pre-authorisation status | Callers ask member services whether a pre-authorisation is approved; the agent has no lookup tool. | yes |
| `complaints` | Complaints | Callers want to make a formal complaint, which policy routes to customer relations. | no — correct escalation |
| `cancellation` | Cancelling a policy | Callers want to cancel; cancellations are handled by a person. | no — correct escalation (below threshold) |
| `caller_requested` | Asked for a person | Callers asked for a person at the start of the call. | no |

Centroids are the normalized mean of member gap-summary embeddings (computed at seed time with the configured embedder).

# Gap summaries (rotate)

* newborn: "How to add a newborn baby to an existing health insurance policy" · "Deadline and medical questions for adding a new baby to the policy" · "Adding a newborn to the policy after the birth"
* prior_auth: "Checking whether a pre-authorisation has been approved" · "Status of a pending pre-authorisation for surgery"
* complaints: "Making a formal complaint about claim handling"

# Human resolution notes (rotate; the evidence fix drafting uses)

**newborn**
1. "Explained a newborn can be added within 3 months of birth with no medical questions; cover starts from the date we are told. Added the baby to the policy; new premium from the next collection."
2. "Added baby to the family policy by phone. Told caller the membership certificate is reissued within 5 working days and the baby shares the family excess."
3. "Told caller to add the baby within 3 months of birth to avoid medical questions; after that the baby joins on moratorium terms."
4. "Caller asked if the baby's hospital stay at birth is covered - no, normal childbirth is not covered; cover starts once the baby is added."
5. "Added newborn on caller's behalf at the child rate; sent an updated premium statement by email."

**prior_auth**
1. "Looked up the pre-authorisation: pending, waiting for the consultant's procedure code; decision expected within 2 working days."
2. "Pre-authorisation approved; gave the code, what it covers and the valid-until date. Caller can book."
3. "Pre-authorisation declined as the condition is excluded; explained the exclusion and the customer relations route."

**complaints**
1. "Logged a formal complaint; acknowledgment within 5 working days and a final response within 8 weeks, after which the Financial Ombudsman Service can review."
2. "Resolved the complaint on the call with an apology; sent a summary resolution communication."

**cancellation** / **caller_requested**: short generic notes ("Cancelled within the 21-day cooling-off period with a full refund", "Answered general questions").

# Sample caller lines (templates)

* newborn: "Hi, I had a baby two weeks ago and I need to add her to my health insurance." / "How do I put my newborn son on my policy?"
* prior_auth: "I'm calling to check whether my pre-authorisation PA-500955 has been approved."
* complaints: "I want to make a complaint. My claim took weeks and then it was declined."

# Acceptance

- **UC-05** — Given the seeded history, when the dashboard summary is requested for `northgate-health`, then it counts 123 calls (82 resolved, 38 escalated, 3 abandoned), and the clusters *Adding a newborn to the policy* (14 escalations) and *Pre-authorisation status* (9) are ready for a fix while *Complaints* is marked as a correct escalation.
