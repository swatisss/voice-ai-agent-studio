---
type: Change Proposal
title: CP-0021 Test suites
description: Editable test scenarios per agent with personas, expected tools and results and stand-in memory; runs of k repeats against the published version, the draft or an earlier version, scored with the call scorer and reported as pass^k; Run tests in the builder, report only.
status: stable
cp_state: implemented
tags: [evaluation, testing, simulation, ui]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-31T00:00:00Z" }
---

# Why

CP-0020 shows how agents do with real callers, but only after a change has reached them. Builders need to check a declarative change before publishing it: does the new rule, document or tool still handle the situations that matter? Today the only simulations run to gate a fix proposal, against six read-only scenarios, once each, judged on four fields. One run per scenario hides flaky behaviour (τ-bench pass^k), and nothing tests tool use, verification against a difficult caller, or memory.

Part 1b of [ADR-0011](/decisions/adr-0011-evaluation-and-self-learning.md); the design decisions are Q1, Q6, Q11, Q12 and Q16 of the session of 2026-10-31. Self-learning (CP-0022) will reuse these runs to gate its proposals.

# What changes

* **Editable test scenarios per agent** (Evaluation → Test suites): caller goal, profile, **persona** (calm, confused, impatient, adversarial), expected outcome, **required tools with key arguments**, **forbidden tools**, **expected tool results**, and stand-in **memory** facts. The seeded Customer Care Agent gets expectations on its six scenarios and two new ones (an adversarial caller who gets the date of birth wrong first, a caller whose remembered preference should be used).
* **Test runs**: every enabled scenario played **k times** (default 3) against the **published version, the draft, or an earlier version**, through the existing simulator. Each simulated call is scored by the CP-0020 scorer with the run's config and the judge always on; expectations are checked in code. A repeat passes when the outcome, goal, hard gates and tool expectations all hold; the run reports **pass^k** (scenarios passing every repeat), pass@k, pass rate, hard fails and per-check pass rates.
* **Triggers**: manual from Evaluation, **Run tests** in the builder (on the draft, report only, never blocks Publish), and automatically on every publish (agent setting, on by default) so each version has a baseline.
* Simulated calls open on the call detail page with their scorecard and a **Simulated** badge. They never count in the Evaluation rollups, Calls list or calibration.
* Proposal evaluation keeps its behaviour and pass rules; eval runs just stop being tied to proposals.

# Affected specs

* New: [/architecture/test-suites.md](/architecture/test-suites.md) (TEST-01…TEST-10).
* [/architecture/evaluation.md](/architecture/evaluation.md) - run kinds; the simulator gets a caller style.
* [/architecture/call-scoring.md](/architecture/call-scoring.md) - simulated calls scored by test runs (SC-01 reworded).
* [/architecture/agent-memory.md](/architecture/agent-memory.md), [/architecture/agent-runtime.md](/architecture/agent-runtime.md) (RT-07) - scenario memory stands in for member memory and is never stored.
* [/architecture/jobs-and-events.md](/architecture/jobs-and-events.md), [/api/events.md](/api/events.md) - `run_test_suite`, `test_run.progress`, `test_run.finished`.
* [/data/data-model.md](/data/data-model.md) - columns on `eval_runs`, `eval_results`, `eval_scenarios` (DM-01 reworded); [/data/agent-config.md](/data/agent-config.md) - `evaluation.test_on_publish` (DM-08 reworded).
* [/api/rest-api.md](/api/rest-api.md) - scenario CRUD, test runs.
* [/prompts/caller-simulator.md](/prompts/caller-simulator.md) - `caller_style` (text below; applied with the implementation because prompts load verbatim).
* [/ui/evaluation.md](/ui/evaluation.md) (UI-51, UI-52), [/ui/agent-builder.md](/ui/agent-builder.md) (UI-53), [/ui/calls.md](/ui/calls.md).
* [/demo-data/evergreen-health.md](/demo-data/evergreen-health.md) - eight scenarios with expectations (UC-04 reworded).
* [/product/glossary.md](/product/glossary.md), [/process/conventions.md](/process/conventions.md) (prefix `TEST`), ADR-0011, index files.

# Acceptance criteria

New: TEST-01…TEST-10, UI-51…UI-53. Changed: SC-01 (the job never scores simulations; test runs score their own), DM-01 (new columns), DM-08 (`test_on_publish` default), UC-04 (eight scenarios), RT-07 (scenario memory). Each is written in its spec.

# Prompt change: caller simulator

Applied to [/prompts/caller-simulator.md](/prompts/caller-simulator.md) with task 4. Variables add `caller_style` (one line from the persona table in [/architecture/test-suites.md](/architecture/test-suites.md); proposal runs pass the `calm` line).

```text
You are role-playing a caller phoning a health insurer's automated assistant. Stay in character.

Your goal: {{caller_goal}}
Your details (share only when asked): {{caller_profile}}
How you behave: {{caller_style}}

Conversation so far:
{{transcript}}

Write only your next line as the caller: one or two short, natural spoken sentences. Answer the assistant's questions using your details, except where how you behave says otherwise. Do not volunteer details before you are asked. Do not help the assistant or suggest answers.
If your goal has been fully answered, or the assistant has transferred you to a person, or the assistant clearly cannot help after you asked twice, reply with exactly [HANGUP].
```

# Tasks

1. Spec edits (done in this CP; the simulator prompt text above was applied with task 4).
2. Data: new columns with defaults, added to existing databases on start; `test_on_publish` — covers DM-01, DM-08.
3. Scenarios: CRUD with validation, seeded expectations and the two new scenarios — covers TEST-10, UC-04.
4. Runner: `run_test_suite` (targets, draft resolution without a version, repeats, personas, scenario memory in the session, scoring with the run's config and judge on, expectation checks, summary, events); proposal runs pass the `calm` style; SC-01 rewording — covers TEST-01…TEST-07, TEST-09, SC-01, RT-07.
5. Triggers: manual and builder endpoints, start on publish and on proposal approval, not from the seeder — covers TEST-05, TEST-08.
6. Web: Evaluation → Test suites (scenarios, form, run, runs, run detail), builder **Run tests** and the setting, Simulated badge and scorecard on simulated calls — covers UI-51…UI-53.
7. Tests with the fake LLM (scripted simulator and judge).

# Risks and rollout

* **Cost**: a default run is scenarios × 3 simulations of up to 8 caller turns plus a judge request each; the seeded agent's eight scenarios make 24 simulations, roughly 400–600 LLM requests per run. Publishing triggers one by default; the per-agent switch turns that off.
* **Shared mock state**: the mock business API keeps module-level state, so expectations check tool **results** in the call, not the state of the business system afterwards. Concurrent runs can change each other's mock records (for example a document request); expected results are chosen to be read-only or idempotent.
* **Schema**: new columns on three existing tables, added on start; `seed --reset` for the new seeded scenarios.
* **Judge reliability**: test verdicts lean on judge checks that may be uncalibrated (CP-0020). Expectations and hard gates decided in code carry most of the pass rule.

# Out of scope

* Gating Publish or proposal approval on test results; held-out sampling; deriving scenarios from failed calls (CP-0022).
* Checking the business system's state after a run (needs per-run isolated mock data).
* Two-session memory tests through real extraction (simulations must not write member memory); scenario memory stands in.
* Audio-level simulation (noise, accents, interruptions) and WER.
* Scenarios shared across agents or tenants; importing or exporting suites.
