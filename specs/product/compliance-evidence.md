---
type: Compliance Note
title: Compliance evidence
description: Each healthcare control the platform enforces, the rule and regulation it answers to, how and where it is enforced, and the acceptance tests that prove it; the Compliance page shows this table with each test's latest result, and the gaps that remain.
status: draft
tags: [product, healthcare, compliance, verification]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-02T00:00:00Z" }
---

# Purpose

"Built for healthcare" is a claim; this page is the evidence ([CP-0035](/changes/cp-0035-compliance-evidence.md)). Each control below answers to a rule in [Healthcare compliance](/product/healthcare-compliance.md), names the regulation it supports, says whether it is enforced **in code** (the runtime cannot do otherwise), by **prompt and score** (the model is told, and every call is checked) or by **process**, and lists the acceptance IDs whose tests prove it. The table is read verbatim at runtime by `GET /api/compliance/evidence`, so the page and this spec cannot disagree. Regulation references show what a control supports; they are not a legal opinion, and no control on its own makes a deployment compliant.

# Controls

| Control | Rule | Regulation it supports | Enforced by | Where | Evidence |
|---|---|---|---|---|---|
| C1 | Identity before PHI: tools that return member data are blocked until a verification tool returns `verified: true` | HIPAA 45 CFR 164.514(h) (verify identity before disclosure) | code | runtime tool gate, realtime bridge, mock business API | TS-01, TS-11, RV-05, OB-03, MOCK-03, SC-03 |
| C2 | Caller ID identifies, it never verifies; first name only until verified | 45 CFR 164.514(h); caller-ID spoofing | code | caller identification, prompt rendering | IDV-01, IDV-03, IDV-06, IDV-07, API-05 |
| C3 | Three failed verifications go to a human | 45 CFR 164.514(h) | code | escalation engine | IDV-04, ES-09 |
| C4 | Minimum necessary: no profile or memory before verification; business API scoped to the verified member | 45 CFR 164.502(b), 164.514(d) | code | prompt rendering, tool headers, mock business API | MEM-06, TS-08, MOCK-05 |
| C5 | Safety screen before any model call: emergency and self-harm language gets the fixed 911 / 988 message and a nurse | duty of care; 988 Suicide & Crisis Lifeline | code | runtime safety screen | ES-01, RT-11, RV-08 |
| C6 | Disclosure: every call opens with the virtual-assistant and recording notice | state bot-disclosure and call-recording notice laws | code | session greeting, front desk | RT-01, RTE-07 |
| C7 | Policy rules, appeals and grievances: never-rules and escalate-when rules become checks on every call; appeals go to a person | plan claims and appeals procedures (for example 29 CFR 2560.503-1) | prompt and score | policy prompt, call scoring | SC-02, SC-14 |
| C8 | Memory without health details, expires, erasable per member, isolated per business unit | 45 CFR 164.502(b); privacy-law deletion rights | code | memory extraction, purge and erase | MEM-04, MEM-07, MEM-08, API-07, MT-13 |
| C9 | Business units are isolated: no request reaches another unit's data | 45 CFR 164.312(a)(1) (access control) | code | repository helpers, `/v1` keys | MT-01, MT-03, MT-04, MT-14, MT-15 |
| C10 | Only a person publishes, and only an admin: learning proposes, a reviewer cannot publish or approve | 45 CFR 164.308(a)(3), 164.312(a)(1) (workforce access) | code | learning run, approval gate, API guard | SL-11, FL-06, AUTH-01, AUTH-03 |
| C11 | Audit trail: every call records the version that answered, who published it and the fix it came from | 45 CFR 164.312(b) (audit controls) | code | agent versions, call detail | AUTH-05, DM-14, CMP-03 |
| C12 | No caller text to hosted processors without a BAA in routing; webhooks carry IDs only | 45 CFR 164.502(e), 164.504(e) (business associates) | code | supervisor routing PHI mode, webhooks | RTE-04, WH-03 |
| C13 | Requests are authentic: signed telephony webhooks, single-use stream tokens, signed webhook deliveries | 45 CFR 164.312(c)(1), 164.312(e)(1) (integrity, transmission security) | code | telephony routes, webhooks | TEL-02, TEL-04, TEL-10, WH-04 |
| C14 | Synthetic data only in every environment | — | process | repo rules, seed data | — |

# Status of a control

`scripts/compliance_check.py` finds the tests whose docstrings cite each evidence ID (`Covers: ID`), runs exactly those tests and writes `apps/api/data/compliance-report.json` (`generated_at`, `commit`, and per ID the test names and `passed` or `failed`). `GET /api/compliance/evidence` combines the table with the latest report:

* an ID is `passed` when all its tests passed, `failed` when any failed, `not_run` when there is no report or the report does not list it, `no_test` when no test cites it;
* a control is `failed` when any of its IDs failed, otherwise `not_run` when any is not run, otherwise `passed`; a control without IDs is `process`.

# Open gaps (shown on the page)

* No Business Associate Agreements yet with the LLM, speech, telephony or cloud providers.
* No PHI redaction before transcripts reach analytics, clustering and drafting.
* No call recording, so no recording-consent handling per jurisdiction.
* No audit-log export or retention policy beyond member memory.
* Two fixed demo accounts, not an identity provider.

# Acceptance

- **CMP-01** — Given no compliance report, when `GET /api/compliance/evidence` is requested, then it lists every control of this table in order with its rule, reference, enforcement, place and evidence IDs, every ID `not_run` or `no_test`, C14 `process`, the open gaps, and `report: null`.
- **CMP-02** — Given `scripts/compliance_check.py` run with one evidence test made to fail, then the report marks that ID `failed` and only that control `failed`; the other controls with tests are `passed`; only tests that cite an evidence ID were run.
- **CMP-03** — Given a call answered by a version that an admin published by approving a fix, then `GET /api/calls/{id}` carries `version_info` with the version number, `published_by`, `published_at`, `change_note` and `source_proposal` (`id`, `title`, `decided_by`, `decided_at`); for a version published from the builder `source_proposal` is `null`.
