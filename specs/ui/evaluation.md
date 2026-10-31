---
type: UI Spec
title: Evaluation
description: How each agent performs, measured - per-version scores and trends, every check with its pass rate and judge calibration, drift flags, and the scored calls behind each number.
status: stable
tags: [ui, evaluation, scoring]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-31T00:00:00Z" }
---

# Page (`/evaluation/?agent=…`)

Scores come from [call scoring](/architecture/call-scoring.md) via `GET /api/evaluation/summary` and `GET /api/evaluation/scorecards` ([/api/rest-api.md](/api/rest-api.md)). Two views as tabs, **Scorecards** (below, real calls) and **Test suites** (`/evaluation/?agent=…&view=tests`, [/architecture/test-suites.md](/architecture/test-suites.md)). Controls: agent select (default the `agent` query parameter, else the first agent), period (7 / 28 / 90 days, default 28), **Include seeded history** (default on). It refreshes on `scorecard.updated` events (topic `evaluation`), at most once every 5 s.

1. **Headline tiles** for the agent's published version: Goal met, Containment, Grounded, Hard fails (count, red when above zero), p95 response time, Helpful (thumbs up share). Each tile shows the change against the previous version when that version has scored calls in the period. A **Drift** badge with the explanation "Lower than in this version's first week" appears on any tile whose metric drifted.
2. **Trend**: daily goal met, containment and grounded (lines) with hard fails (bars) for the period; version publish dates are marked on the axis.
3. **Versions**: one row per version with scored calls in the period: version and publish date, calls, scored, containment, correct and unnecessary escalation, abandonment, goal met, grounded, tool success, hard-fail calls, p50 / p95 latency, Helpful. Selecting two rows shows the per-check difference in pass rate.
4. **Checks**: grouped by Outcome, Responsiveness, Knowledge, Tools, Memory and Safety. Each row: text, *Code* or *Judge* tag, *Hard gate* badge, source (*Built-in*, *From your policy*, *Custom*), pass rate and decided count, and for judge checks the reviews, agreement, catch rate and baseline with a **Calibrated** (ok) or **Uncalibrated** (neutral, tooltip "Needs 20 reviews at 85 % agreement") badge. Clicking a row filters the call list to calls that failed it.
5. **Scored calls**: started, version, outcome, Helpful / Not helpful, score, *Hard fail* badge, failed checks (first three and "+n"), reviewed count; filters: version, check, verdict, hard fail only, not yet reviewed. Row click opens the call detail with its Scorecard card ([/ui/calls.md](/ui/calls.md)).

Empty state (no scored calls): "No scored calls for this agent yet. Calls are scored automatically after they end." with a **Test call** link. Percentages show "—" when there is nothing to count.

# Test suites view

1. **Scenarios**: name, persona, expected outcome, counts of required tools, forbidden tools, expected results and memory facts, enabled switch, and the latest result as "3/3" (ok), "2/3" (warn) or "0/3" (bad). **New scenario** and row **Edit** open a form with every scenario field: tools are chosen from the agent's tools, arguments as key/value rows, the caller profile as name, member ID, date of birth and extra key/value facts; **Delete** asks for confirmation. API errors show next to the field.
2. **Run suite**: target select (*Published vN*, *Draft*, each earlier version) and repeats (1–5, default 3). While a run is going the button shows its progress ("7 of 18") from `test_run.progress`; a second start is refused with the API's message.
3. **Runs**: started, target and version, trigger (*Manual*, *Builder*, *On publish*), status, **all runs passed** (pass^k, e.g. "4 of 6 scenarios"), pass rate, hard fails and a *Text approximation* label for realtime agents.
4. **Run detail** (row click): a grid of scenarios × repeats with ✓ / ✕ cells; a cell shows its failures and links to the simulated call's detail; the run's per-check pass rates; and, when an earlier finished run of the same agent exists, the change per scenario against it.

Empty state (no scenarios): "No test scenarios yet. Add the situations this agent must handle." with **New scenario**.

The agent builder's Evaluation tab links here ([/ui/agent-builder.md](/ui/agent-builder.md)); from Insights, a cluster's evidence call opens its call detail, where the scorecard sits next to the analysis.

# Acceptance

- **UI-47** — Given the seeded `evergreen-care` agent, when Evaluation opens with seeded history included, then the tiles show the published version's goal met and grounded rates, the Grounded tile carries a Drift badge, the Checks list shows *Grounded* with 5 failed calls, and clicking it lists exactly those 5 calls.
- **UI-51** — Given the Test suites view of the seeded Customer Care Agent, then its eight scenarios are listed with persona and expectations; adding a scenario with a required tool and its argument saves it and lists it; a scenario naming an unknown tool shows the API's error.
- **UI-52** — Given a suite run started from the view, then the button shows progress as results arrive, the run appears in Runs when finished with its pass^k and pass rate, and its detail grid links each cell to a simulated call whose detail shows the call's scorecard.
- **UI-50** — Given a judge check with 20 reviews at 85 % agreement and another with 3 reviews, then the first shows **Calibrated** and the second **Uncalibrated**; given an agent with no scored calls, then the empty state and the Test call link are shown and no tile shows a number.
