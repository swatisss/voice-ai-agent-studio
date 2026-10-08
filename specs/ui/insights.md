---
type: UI Spec
title: Insights
description: Cluster list with impact, cluster detail with evidence, fix proposal review, live evaluation results, and approve or reject.
status: stable
tags: [ui, insights, learning]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

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
   * kind badge, title, rationale;
   * payload view: article rendered as Markdown with an **Edit** toggle (textarea) — or skill + tool definitions (`JsonView` + edit);
   * **Run evaluation** button → live progress bar from `eval.progress` and a results grid: rows = cases (cluster cases then regressions), columns = Baseline / Candidate, cells ✓/✕ with judge notes on hover/click;
   * summary: "Baseline 0/6 → Candidate 5/6 (+83 pts) · Regressions 6/6 passed";
   * **Approve & publish** (enabled per [/architecture/fleet-learning.md](/architecture/fleet-learning.md) rules; disabled state explains why) and **Reject** (note required).
4. After approval: success banner "Published v2 — From fix: …" with links to the agent versions and a **Test it now** button (opens test call).

# Acceptance

- **UI-15** — Given a ready cluster, when Draft fix is clicked, then a spinner shows until the `proposal.updated` event arrives and the proposal renders without reload.
- **UI-16** — Given an eval running, then the progress bar and grid update per case-arm as events arrive.
- **UI-17** — Given an eval with a regression failure, then Approve is disabled with the reason "1 regression failed".
- **UI-37** — Given a cluster that contains a resolved call whose caller marked it "Not helpful", then the cluster card shows its not-helpful count, the evidence table lists that call with the comment, and the call counts toward "n of 5".
