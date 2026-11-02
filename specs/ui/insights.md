---
type: UI Spec
title: Insights
description: Cluster list with impact, cluster detail with evidence, fix proposal review, live evaluation results, and approve or reject.
status: stable
tags: [ui, insights, learning]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Needs attention (top of `/insights/`)

From `GET /api/insights/actions` ([/architecture/learning-actions.md](/architecture/learning-actions.md)), refreshed on `action.updated`: one row per open action, ranked; a red dot for high severity; kind label (*Fix did not hold*, *Answer needed*, *Check failing*, *Review calls*, *Drift*, *Test failing*), title, detail, agent name, a link for the next step (the cluster, the listed calls on Evaluation filtered by the check, Evaluation for the version, the test run, the agent's Versions tab), and **Done** / **Dismiss** (each asks for an optional note). An *Answer needed* row opens an inline form: "What should the agent tell callers?" (textarea, at least 20 characters) and **Save answer & draft fix**, which shows "Drafting and evaluating…" until the proposal arrives in Waiting for review. Empty: "Nothing needs attention. Learning runs list what they find here." Hidden when the agent filter selects an agent with none.

# Learning inbox

* **Last night** strip from `GET /api/learning/runs`: when the last run finished, calls reviewed, signals by kind, proposals drafted and how many passed the gate; **Run now** (starts a run; disabled while one runs; the strip refreshes on `learning.run.finished`).
* **Waiting for review** (`GET /api/insights/inbox`): one card per proposal — *Nightly* or *Manual* badge, kind, title, cluster, rationale, gate badge (**Passed** ok / **Failed** bad with its reasons), lift on cluster and held-out cases, regressions, and an **Open** link to the proposal panel of its cluster. Empty: "Nothing waiting. Proposals drafted overnight appear here."

# Cluster list (`/insights/`)

Agent select. Summary strip: open clusters, fixable clusters ready, escalations/week in fixable clusters, potential weekly savings. Cards sorted by est. weekly cost: name, description, root cause badge, escalations (28 d) and per week, **not-helpful calls (28 d)** (shown when above zero), est. weekly cost, last seen, status/label:

* **Ready for fix** (accent) with **Draft fix** button,
* **Fix proposed** / **Fixed in vN** (ok) with the fix line "Held: 1.5/week → 0/week" once `fix.held`, or **Fix did not hold** (bad) when the cluster was reopened,
* **Correct escalation — no fix** (neutral),
* **Investigate** (warn),
* below threshold: "Watching (n of 5)", where n counts escalations and thumbs-down calls together (`signal_count`, [/architecture/fleet-learning.md](/architecture/fleet-learning.md)).

# Cluster detail (`/insights/cluster/?id=…`)

1. Header with stats and status; **Draft fix** / **Ignore**; the fix line (before and after per week). When `needs_answer`, **Draft fix** is replaced by the answer form of *Needs attention* ("No specialist has answered these callers yet. What should the agent tell them?"); a saved `human_answer` is shown with who gave it.
2. **Evidence**: table of member calls — date, caller goal, gap summary, human resolution note, **caller feedback** ("Helpful" / "Not helpful" and the comment), link to call. Calls the agent resolved but the caller marked "Not helpful" are listed here like escalations.
3. **Proposal** panel (when one exists):
   * kind badge, *Nightly* / *Manual* badge, title, rationale;
   * payload view: article rendered as Markdown with an **Edit** toggle (textarea); for `knowledge_edit` a side-by-side of the current and revised article with changed paragraphs highlighted; for `tool_attach` the tool's name, description and endpoint; or skill + tool definitions (`JsonView` + edit); and the derived scenarios;
   * **Run evaluation** button → live progress bar from `eval.progress` and a results grid: rows = cases (cluster, held-out, derived, then test scenarios), columns = Baseline / Candidate, cells ✓/✕ (or "2/3" for repeated scenarios) with failures and a link to the simulated call;
   * summary: "Baseline 0/12 → Candidate 10/12 (+83 pts) · Held out 2/2 · No regressions · p95 1.2 s → 1.2 s" (runs, with `case_repeats`) and the gate badge with its reasons; warnings in a neutral note below ("Slower: p95 264 ms against 36 ms, within the 2000 ms budget");
   * **Approve & publish** (enabled when the gate passed; otherwise a **Publish anyway** link asks for a note and sends `force`) and **Reject** (note required; says the cluster is snoozed for `snooze_days`).
4. After approval: success banner "Published v2 — From fix: …" with links to the agent versions and a **Test it now** button (opens test call); with `draft_kept`, a second line "Your unpublished draft changes were kept as a draft, with this fix added."

# Acceptance

- **UI-67** — Given open actions of each kind, then Needs attention lists them ranked with their kind labels and next-step links; **Dismiss** removes a row without reload; the dashboard's Self-learning card shows the open count.
- **UI-68** — Given a cluster with `needs_answer`, then its detail shows the answer form instead of **Draft fix**; saving an answer of at least 20 characters shows "Drafting and evaluating…" and then the proposal with its gate; a fixed cluster shows its fix line, and a reopened one *Fix did not hold*.
- **UI-54** — Given a finished nightly run that drafted two proposals, then the Last night strip shows its counts and both proposals are under Waiting for review with a *Nightly* badge and their gate; approving one removes it from the inbox and shows the published version.
- **UI-15** — Given a ready cluster, when Draft fix is clicked, then a spinner shows until the `proposal.updated` event arrives and the proposal renders without reload.
- **UI-16** — Given an eval running, then the progress bar and grid update per case-arm as events arrive.
- **UI-17** — Given an eval whose gate failed because a test scenario regressed, then Approve is disabled and the gate's reason names the scenario; **Publish anyway** requires a note.
- **UI-37** — Given a cluster that contains a resolved call whose caller marked it "Not helpful", then the cluster card shows its not-helpful count, the evidence table lists that call with the comment, and the call counts toward "n of 5".
