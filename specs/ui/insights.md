---
type: UI Spec
title: Insights
description: Cluster list with impact, cluster detail with evidence, fix proposal review, live evaluation results, and approve or reject.
status: draft
tags: [ui, insights, learning]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Learning inbox (top of `/insights/`)

* **Last night** strip from `GET /api/learning/runs`: when the last run finished, calls reviewed, signals by kind, proposals drafted and how many passed the gate; **Run now** (starts a run; disabled while one runs; the strip refreshes on `learning.run.finished`).
* **Waiting for review** (`GET /api/insights/inbox`): one card per proposal — *Nightly* or *Manual* badge, kind, title, cluster, rationale, gate badge (**Passed** ok / **Failed** bad with its reasons), lift on cluster and held-out cases, regressions, and an **Open** link to the proposal panel of its cluster. Empty: "Nothing waiting. Proposals drafted overnight appear here."

# Cluster list (`/insights/`)

Agent select. Summary strip: open clusters, fixable clusters ready, escalations/week in fixable clusters, potential weekly savings. Cards sorted by est. weekly cost: name, description, root cause badge, escalations (28 d) and per week, **not-helpful calls (28 d)** (shown when above zero), est. weekly cost, last seen, status/label:

* **Ready for fix** (accent) with **Draft fix** button,
* **Fix proposed** / **Fixed in vN** (ok),
* **Correct escalation — no fix** (neutral),
* **Investigate** (warn),
* below threshold: "Watching (n of 5)", where n counts escalations and thumbs-down calls together (`signal_count`, [/architecture/fleet-learning.md](/architecture/fleet-learning.md)).

# Cluster detail (`/insights/cluster/?id=…`)

1. Header with stats and status; **Draft fix** / **Ignore**.
2. **Evidence**: table of member calls — date, caller goal, gap summary, human resolution note, **caller feedback** ("Helpful" / "Not helpful" and the comment), link to call. Calls the agent resolved but the caller marked "Not helpful" are listed here like escalations.
3. **Proposal** panel (when one exists):
   * kind badge, *Nightly* / *Manual* badge, title, rationale;
   * payload view: article rendered as Markdown with an **Edit** toggle (textarea); for `knowledge_edit` a side-by-side of the current and revised article with changed paragraphs highlighted; for `tool_attach` the tool's name, description and endpoint; or skill + tool definitions (`JsonView` + edit); and the derived scenarios;
   * **Run evaluation** button → live progress bar from `eval.progress` and a results grid: rows = cases (cluster, held-out, derived, then test scenarios), columns = Baseline / Candidate, cells ✓/✕ (or "2/3" for repeated scenarios) with failures and a link to the simulated call;
   * summary: "Baseline 0/6 → Candidate 5/6 (+83 pts) · Held out 2/3 · No regressions · p95 1.2 s → 1.2 s" and the gate badge with its reasons;
   * **Approve & publish** (enabled when the gate passed; otherwise a **Publish anyway** link asks for a note and sends `force`) and **Reject** (note required; says the cluster is snoozed for `snooze_days`).
4. After approval: success banner "Published v2 — From fix: …" with links to the agent versions and a **Test it now** button (opens test call).

# Acceptance

- **UI-54** — Given a finished nightly run that drafted two proposals, then the Last night strip shows its counts and both proposals are under Waiting for review with a *Nightly* badge and their gate; approving one removes it from the inbox and shows the published version.
- **UI-15** — Given a ready cluster, when Draft fix is clicked, then a spinner shows until the `proposal.updated` event arrives and the proposal renders without reload.
- **UI-16** — Given an eval running, then the progress bar and grid update per case-arm as events arrive.
- **UI-17** — Given an eval whose gate failed because a test scenario regressed, then Approve is disabled and the gate's reason names the scenario; **Publish anyway** requires a note.
- **UI-37** — Given a cluster that contains a resolved call whose caller marked it "Not helpful", then the cluster card shows its not-helpful count, the evidence table lists that call with the comment, and the call counts toward "n of 5".
