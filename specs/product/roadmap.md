---
type: Product Brief
title: Roadmap
description: Candidate features after v1, ranked P0-P2, from the 2026-11-01 end-user review and a competitor survey; each becomes a change proposal before it is built.
status: stable
tags: [product, roadmap]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-01T00:00:00Z" }
---

# How to read this

These are **candidates**, not commitments. Nothing here changes behavior. Each item becomes a change proposal ([/process/sdd-workflow.md](/process/sdd-workflow.md)) when it is picked up, and its status here moves from *candidate* to *CP-NNNN*. Sources:

* a hands-on review on 2026-11-01 that built a new agent from scratch in the sandbox business unit and followed it through test calls, scoring, escalation and self-learning ([/product/demo-walkthrough.md](/product/demo-walkthrough.md) repeats that walk);
* a survey of competitor product docs and changelogs on 2026-11-01 (Retell AI, Vapi, Bland, Synthflow, ElevenLabs Agents, PolyAI, Sierra, Decagon, Cognigy, Hippocratic AI; evaluation tools Hamming, Coval, Cekura, Langfuse). Items marked *vendor claim* rest on marketing pages only.

Priorities: **P0** blocks real customers or safety; **P1** clear value for the next release; **P2** differentiators.

# Proposed and built

| Item | Status |
|---|---|
| Full knowledge chunks, sound "never" checks, verification only where the agent can verify | [CP-0030](/changes/cp-0030-knowledge-judge-verification-fixes.md), implemented |
| Website knowledge sources: crawl a site from one URL, keep it in sync, answer with page citations | [CP-0031](/changes/cp-0031-website-knowledge-sources.md), implemented |

# From the end-user review

| # | Feature | Why | Pri |
|---|---|---|---|
| R1 | **Caller ID that the agent cannot ignore**: on an identified call the server supplies the member reference to the verification tool and fills `{first_name}` in the greeting | The model ignored flow A and passed a first name as the member ID | P0 |
| R2 | **Memory never records permissions**: "says Raj may call" instead of "Raj is authorized"; a remembered preference the tools cannot honor is said out loud | A casual remark became an authorization; a text preference was silently overridden | P0 |
| R3 | **Configuration root cause**: analysis gains `configuration` (no verification tool, tool misconfigured); such calls raise setup alerts on the agent instead of learning clusters | A setup problem was filed as missing knowledge | P0 |
| R4 | **Setup checklist and guided empty states**: Overview shows Knowledge → Skills → Rules → Test scenario → Publish with progress; each empty tab explains itself with an example; clickable example rules; starter templates (FAQ agent, claims intake) | New builders face 11 tabs with no guidance | P0 |
| R5 | **Publish confirmation**: "v1 is live", what changed since the last version, next steps (Test call, Add scenarios, Run tests); offer to run the suite; warn when the agent has no scenarios | Publishing gives no feedback | P1 |
| R6 | **Members page**: search by member ID or phone (masked), agents holding memory, Export and Erase, an erasure audit log, link from the escalation console | Erasure requests have no entry point; memory is reachable only from one call | P0 |
| R7 | **Self-learning drafts bundles**: a fix may combine an article with a policy rule or skill ("when knowledge answers fully, do not offer a specialist unless asked") | The newborn article worked but the agent still offered a hand-off | P1 |
| R8 | **Explain a failed gate and redraft**: show each failing replay's last turns and a one-line reason; **Revise draft** sends the failures back to the drafter | Reviewers see "Check failed" with nowhere to go | P1 |
| R9 | **Realistic simulated callers**: the simulated caller ends once its goal is answered, does not invent new goals, and does not accept a specialist offer it did not need; an empty caller profile is described as "an existing customer whose details are not needed" rather than "not a member" | Replays escalated only because the caller said yes; in the demo run the simulated caller got the right answer, then asked "I'm not a member yet, how can I sign up?" and accepted a specialist | P0 |
| R10 | **Flaky scenario quarantine**: a scenario that is not 3/3 on the live version is shown as *flaky* and left out of the regression count until fixed | The seeded suite fails itself (0/3, 1/3), so "no regressions" is weak | P1 |
| R11 | **Caller-perceived latency and job isolation**: measure from the caller's message to the first reply including routing; run evaluation and learning jobs in a separate worker or with a concurrency cap | A routed reply took over 15 s during a 72-call evaluation while the call recorded 728 ms | P1 |
| R12 | **Packet honesty**: the groundwork packet says "found, not used" when a search hit did not answer the question | The packet said "found" for a question the caller was told had no answer | P2 |
| R13 | **Playground polish**: refocus the chat box after each reply; no demo-tenant callers or placeholders in other business units; agent names in "Recent versions" | Small frictions in every session | P2 |

# From the competitor survey

| # | Feature | Seen at | Why it matters here | Pri |
|---|---|---|---|---|
| C1 | **Call → regression test in one click** (and automatically for every escalation a fix is drafted for) | Cognigy Simulator, Hamming, Cekura (vendor claim), Langfuse datasets | Closes the loop between real failures and the test suite | P0 |
| C2 | **Generate test scenarios from knowledge and skills** (personas × situations × success criteria) | Sierra (vendor claim), Cognigy Simulator | Non-technical builders will not write suites by hand | P0 |
| C3 | **Regression gate on publish** (warn or block when the suite drops against the live version), multi-run for flaky outputs, CLI for CI | ElevenLabs agent testing, Coval GitHub Actions | Publishing has no quality gate today | P0 |
| C4 | **Runtime guardrails**: rules checked on each reply before it is spoken (blocking or logging), not only in the prompt | ElevenLabs guardrails, Hippocratic Polaris (vendor claim) | "Never" items are instructions, not enforcement | P0 |
| C5 | **PHI/PII redaction** of transcripts and recordings per entity type, before data feeds learning or test generation | Retell PII redaction | Baseline healthcare requirement | P0 |
| C6 | **Tool mocking in tests** (mock, real or forced error) and tests that start mid-conversation | ElevenLabs, Vapi simulations | Test failure paths without touching real systems | P1 |
| C7 | **Gradual rollout and A/B experiments** (10 → 25 → 50 → 100 %, sticky per caller, significance) | ElevenLabs experiments, Sierra (vendor claim) | Approved fixes reach a slice of traffic first | P1 |
| C8 | **Custom post-call extraction fields** (boolean, enum, number, text) sent to webhooks | Retell post-call analysis, ElevenLabs data collection | Turns calls into structured operational data | P1 |
| C9 | **Ask your calls**: natural-language analytics over calls with clickable call ids | PolyAI Smart Analyst | Actionable insight for operations managers | P1 |
| C10 | **Per-turn retrieved sources** in call review with inline document preview | PolyAI | Shows why the agent said something | P1 |
| C11 | **Voice-specific metrics and alerts** (speech-to-text, model and text-to-speech time to first byte, interruptions) | Coval, Cekura (vendor claim) | Judge scorecards miss voice failures | P1 |
| C12 | **Template gallery** (healthcare FAQ, scheduling, claims intake) | Retell templates | From a blank page to a working agent | P1 |
| C13 | **Review queues** with assignment and auto-routing by score | Langfuse annotation queues, PolyAI annotations | Scales judge calibration across reviewers | P2 |
| C14 | **Knowledge conflict and gap detection** (articles that disagree; gaps ranked by escalation cost) | Not found at the surveyed vendors (secondary sources only) | A differentiator that fits escalation clustering | P2 |
| C15 | **Build or edit an agent from a written brief**, on a draft with a diff and a simulation before publishing | Bland Norm | Conversational building for non-technical users | P2 |

# North star: connect your own systems

Tools stay developer-facing in v1: a tool is a URL, a method and a JSON Schema ([/architecture/tools-and-skills.md](/architecture/tools-and-skills.md)). Customers connect their own systems in a later release through a **Connections** section:

* managed authentication per business unit (bearer token, basic, custom headers, OAuth2 client credentials), stored encrypted in the tenant vault and attached to tools by reference (ElevenLabs workspace auth connections);
* **Test this tool** with sample input and the real response shown before the tool is used in a skill (Vapi, CLI);
* pre-built connectors for CRM, scheduling and messaging, and MCP servers as a tool source (Synthflow, Retell, ElevenLabs MCP);
* healthcare connectors (FHIR, eligibility and scheduling systems).

Until then, onboarding a customer's system is a professional-services step: the platform team defines the tools for the business unit.
