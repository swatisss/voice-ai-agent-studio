---
type: UI Spec
title: Compliance page
description: The /compliance/ page - each healthcare control with its status from the latest test report, the rule and regulation it supports, how it is enforced, its evidence tests, and the open gaps.
status: stable
tags: [ui, compliance, healthcare]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-02T00:00:00Z" }
---

# Page (`/compliance/`)

Data: `GET /api/compliance/evidence` ([/product/compliance-evidence.md](/product/compliance-evidence.md)). Readable by both roles ([/architecture/studio-auth.md](/architecture/studio-auth.md)).

* **Header**: title "Compliance evidence", one line "Each control is enforced by the platform and proven by tests. Regulation references show what a control supports; they are not a legal opinion." Then the report line: "Tests run {relative time} on commit {short sha}: {passed} of {total} controls passing", or "No test report yet. Run `python scripts/compliance_check.py`."
* **Controls table** (one row per control, in spec order): control id; the rule; the regulation; an enforcement badge (**Code**, **Prompt & score**, **Process**); a status chip (**Passed** green, **Failed** red, **Not run** grey, **Process** neutral). Expanding a row lists its evidence IDs, each with its status (Passed, Failed, Not run, No test) and the test names behind it.
* **Open gaps**: the gaps from the spec as a list headed "Not yet in place".
* At 375 px the table becomes stacked cards with the same content.

# Acceptance

- **UI-71** — Given a compliance report in which every evidence test passed, when the Compliance page opens, then it lists the 14 controls in order with their enforcement badges, every control with tests shows **Passed**, C14 shows **Process**, expanding C1 lists TS-01 with its test names, and the open gaps list mentions Business Associate Agreements; with no report every control with tests shows **Not run** and the header tells how to run the check.
