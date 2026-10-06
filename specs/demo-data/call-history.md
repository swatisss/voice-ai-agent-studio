---
type: Seed Data
title: Synthetic call history
description: Design of the ~120 historical calls seeded for the Member Services agent - volumes, intents, outcomes, clusters, analyses and human resolution notes.
status: stable
tags: [demo-data, seed, learning]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Window and generator

* Four weeks: 2026-09-07 → 2026-10-04 (Mon–Sun weeks), business hours, deterministic RNG seed `42`.
* Channel `voice`, agent version v1, `is_seed: true`, analyses with `source: seed` (no LLM needed to seed).
* Each call gets a short transcript (4–10 events) from templates, consistent with [/demo-data/members-and-claims.md](/demo-data/members-and-claims.md); costs ≈ $0.004–0.012; latency 650–1,400 ms.

# Mix (123 calls)

| Intent | Count | Outcome | Root cause | `cluster_key` |
|---|---|---|---|---|
| `claim_status` | 30 | resolved | none | — |
| `benefits_deductible` | 22 | resolved | none | — |
| `id_card_replacement` | 12 | resolved | none | — |
| `find_provider` | 10 | resolved | none | — |
| `copay_question` | 8 | resolved | none | — |
| `add_dependent_newborn` | 14 | escalated (`knowledge_gap`) | `missing_knowledge` | `newborn` |
| `prior_auth_status` | 9 | escalated (`capability_gap`) | `missing_skill` | `prior_auth` |
| `claim_appeal` | 8 | escalated (`policy_required`) | `policy_required` | `appeals` |
| `provider_billing_dispute` | 3 | escalated (`policy_required`) | `policy_required` | `billing_dispute` |
| `speak_to_person` | 4 | escalated (`caller_requested`) | `caller_requested` | `caller_requested` |
| abandoned (mixed intents) | 3 | abandoned | other | — |

Weekly volume grows slightly (27, 30, 32, 34); newborn escalations are spread 3, 3, 4, 4 so the cluster is "recent and growing". Resulting containment ≈ 68%.

# Clusters (created directly from `cluster_key`)

| key | name | description | fixable |
|---|---|---|---|
| `newborn` | Adding a newborn to coverage | Callers want to know how and when to add a new baby to their plan; no approved article exists. | yes |
| `prior_auth` | Prior authorization status | Callers want the status of a prior authorization; the agent has no lookup tool. | yes |
| `appeals` | Claim denial appeals | Callers want to appeal denied claims, which policy routes to specialists. | no — correct escalation |
| `billing_dispute` | Provider billing disputes | Callers dispute provider bills; requires investigation by a specialist. | no — correct escalation (below threshold) |
| `caller_requested` | Asked for a person | Callers asked for a person at the start of the call. | no |

Centroids are the normalized mean of member gap-summary embeddings (computed at seed time with the configured embedder).

# Gap summaries (rotate)

* newborn: "How to add a newborn to an existing plan" · "Deadline and steps to enroll a new baby on the policy" · "Adding a newborn dependent after birth"
* prior_auth: "Checking the status of a prior authorization" · "Whether a pending prior authorization has been decided"
* appeals: "Filing an appeal for a denied claim"

# Human resolution notes (rotate; the evidence fix drafting uses)

**newborn**
1. "Explained newborns can be added within 60 days of birth as a qualifying life event; coverage is retroactive to the date of birth. Walked her through member portal > Coverage > Life events > Add a dependent."
2. "Added baby by phone. Needs birth certificate or hospital birth record uploaded within 30 days; SSN can be added later. Premium may change at next bill."
3. "Told caller the 60-day window from birth; if missed, must wait for open enrollment. Baby's ID card mails in 7-10 business days, digital card in the app within 2 business days."
4. "Caller asked if hospital stay is covered for baby — yes once added within 60 days, retroactive to birth. Sent portal instructions (Coverage > Life events)."
5. "Submitted add-dependent request on caller's behalf; reminded her to upload the hospital birth record within 30 days to avoid termination of the dependent."

**prior_auth**
1. "Looked up PA in UM system: pending clinical review, decision expected within 2 business days; told caller provider will be notified."
2. "PA approved; gave approval and valid-through dates. Caller can schedule the procedure."
3. "PA denied for insufficient documentation; explained provider can resubmit with additional records."

**appeals**
1. "Filed standard appeal for denied claim; explained 30-day decision timeline and mailed confirmation letter."
2. "Started expedited appeal (urgent); decision within 72 hours."

**billing_dispute** / **caller_requested**: short generic notes ("Opened billing review ticket", "Answered general questions").

# Sample caller lines (templates)

* newborn: "Hi, I just had a baby two weeks ago and I need to add her to my insurance." / "How do I put my newborn son on my plan?"
* prior_auth: "I'm calling to check on a prior authorization for my knee surgery, PA-77930."
* appeals: "My claim was denied and I want to appeal."
