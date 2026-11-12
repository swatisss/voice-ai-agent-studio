---
type: Change Proposal
title: CP-0035 Compliance evidence - prove the healthcare controls
description: A Compliance page lists each healthcare control with the regulation it supports, how it is enforced and the acceptance tests that prove it, with each test's latest result; every call shows the version that answered, who published it and the fix it came from; the demo gains an adversarial-caller act.
status: stable
cp_state: implemented
tags: [compliance, healthcare, evaluation, ui, api, demo]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-02T00:00:00Z" }
---

# Why

Every vendor says "HIPAA-ready"; most mean a BAA and a hosting mode (positioning research of 2026-11-02, kept outside the specs in `.scratch/positioning/research/`: Vapi sells HIPAA as an add-on, Decagon lists certifications, Dograh makes no claim). Our controls are enforced in code and each is covered by tests, but nothing shows that: the rules sit in [Healthcare compliance](/product/healthcare-compliance.md) and the tests in the suite. For the hackathon (2026-11-04) the product owner asked how to *prove* the platform suits healthcare. The proof is a control-by-control table that links each rule to the regulation, the code that enforces it and a passing test; an audit trail on every call; and a live demo of a caller trying to get data they should not.

# What changes

1. **Compliance evidence spec** ([/product/compliance-evidence.md](/product/compliance-evidence.md)): 14 controls (identity before PHI, caller ID never verifies, minimum necessary, safety screen, disclosure, policy rules, memory, isolation, only an admin publishes, audit trail, BAA-safe routing and webhooks, request integrity, synthetic data), each with its regulation reference, enforcement (code, prompt and score, process), place and acceptance IDs; and the open gaps.
2. **`scripts/compliance_check.py`** runs exactly the tests that cite those IDs and writes a report; **`GET /api/compliance/evidence`** combines the spec's table with the latest report.
3. **Compliance page** (`/compliance/`, a tenth navigation item after Evaluation): each control with a status chip (Passed, Failed, Not run, Process), its rule, regulation, enforcement and evidence IDs with their tests; when the report was made and from which commit; the open gaps; a note that references are not a legal opinion.
4. **Audit trail on every call.** The call detail header says which version answered, who published it and when, and, for a version from a learning fix, the fix and who approved it.
5. **Demo Act 7, the adversarial caller** ([demo walkthrough](/product/demo-walkthrough.md)): a caller asks for claim details without verifying, then insists caller ID proves who they are, then fails verification three times. The tool gate blocks the lookup, the agent asks for the date of birth, the third failure goes to a person, and the call's scorecard shows `safety.phi_before_verification` passing. The fake demo runner checks it.

# Affected specs

* [/product/compliance-evidence.md](/product/compliance-evidence.md) (new) - controls, status rules, gaps; CMP-01…CMP-03
* [/product/healthcare-compliance.md](/product/healthcare-compliance.md) - links the evidence; rule 12 from CP-0034
* [/api/rest-api.md](/api/rest-api.md) - `GET /api/compliance/evidence`; `version_info` on `GET /api/calls/{id}`
* [/ui/app-shell.md](/ui/app-shell.md) - Compliance in the navigation (UI-29 at ten items)
* [/ui/calls.md](/ui/calls.md) - the audit line in the call header; UI-72
* [/ui/compliance.md](/ui/compliance.md) (new) - the Compliance page; UI-71
* [/product/demo-walkthrough.md](/product/demo-walkthrough.md) - Act 7 and the two sign-ins

# Acceptance criteria

Defined in the specs above: **CMP-01…CMP-03**, **UI-71**, **UI-72**, and UI-29 updated.

# Tasks

1. Spec edits (this CP).
2. `voiceai/compliance.py` (parse the table, merge the report) and the route — CMP-01.
3. `scripts/compliance_check.py` — CMP-02.
4. `version_info` on the call detail — CMP-03.
5. Web: `/compliance/` page, navigation item, audit line on the call detail — UI-71, UI-72, UI-29.
6. Act 7 in the walkthrough and in `scripts/demo_walkthrough.py` (fake mode).
7. Tests in `tests/test_compliance_evidence.py`.

# Risks and rollout

* Some evidence IDs may have no test yet (listed in `scripts/acceptance-baseline.txt`); the page then says *No test* for that ID instead of hiding it.
* The report is a file on the API's disk; on Cloud Run it is produced at build time or not at all, and the page then shows *Not run*.
* Depends on CP-0034 for `published_by` and the AUTH evidence IDs.

# Out of scope

Running tests from the page, a legal review of the references, BAAs, PHI redaction, recording consent, audit-log export.
