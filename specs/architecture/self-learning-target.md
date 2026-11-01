---
type: Spike Report
title: How self-learning should work
description: A review of the evaluation and self-learning loop as built (what works, verified end to end on 2026-11-01), the gaps that stop it correcting agents reliably, and the target loop; each gap is a roadmap item that becomes a change proposal before it is built.
status: draft
tags: [architecture, learning, evaluation, review]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-01T00:00:00Z" }
---

# Why this document

The product owner asked on 2026-11-01 whether the evaluation and self-learning loop actually corrects agents, whether evaluation drives any action, and whether the demo shows it. This is the answer: a review of the loop as built ([self-learning](/architecture/self-learning.md), [fleet learning](/architecture/fleet-learning.md), [evaluation](/architecture/evaluation.md), [call scoring](/architecture/call-scoring.md), [test suites](/architecture/test-suites.md)) and the loop it should become. **Nothing here changes behavior.** Each gap is a [roadmap](/product/roadmap.md) item (R14–R20) that goes through a change proposal when it is picked up.

# Verdict

**The loop works end to end for its main path**: a recurring gap that callers escalate and specialists resolve becomes a drafted fix, the fix is proven against the current version, a person approves it, a new version is published, and the same question is then answered without a specialist. [Act 6 of the demo walkthrough](/product/demo-walkthrough.md) shows exactly this, and `python scripts/demo_walkthrough.py --learning` runs it unattended (fake mode, 2026-11-01: five bad calls, a cluster ready at 5 of 5 signals, one `knowledge_article` drafted from the specialists' note, gate passed, v2 published, the retry answered "up to 30 extra days" without a hand-off; 45 checks passed, 0 failed).

**It is not yet reliable enough to trust unattended**, for four reasons, in order of risk:

1. What gets published is not what was proven (R14).
2. Nobody checks whether a published fix worked, and a fix that did not work is never revisited (R15).
3. The gate's verdict is noisy: the same fix passes one run and fails the next (R16).
4. Two of the loop's inputs are weak: "no answer" from knowledge search almost never fires (R17), and a draft may be grounded in the AI's own summary rather than a human's answer (R18).

Evaluation is mostly **observed, not acted on**: scorecards, drift flags and failing test scenarios are shown but create nothing for anyone to do (R20).

# The loop as built

| Stage | What happens | Where |
|---|---|---|
| Signals | Real calls with an escalation, a thumbs down, a no-answer knowledge search, a tool error, a hard-gate fail or a *calibrated* judge fail | `learning/nightly.py` `signals_of` |
| Diagnose | `analyze_call` gives a root cause and a gap summary; a call with signals is re-analysed so it never stays `none` | `learning/analyze.py` |
| Cluster | Gap summaries are embedded and joined to the nearest cluster (or a new one) | `assign_cluster` |
| Ready | A fixable, `open`, unsnoozed cluster with at least `FL_MIN_CLUSTER_SIZE` (5) signals in 28 days | `learning/impact.py` |
| Draft | One typed change (article, article edit, tool, skill, rule) from up to 10 evidence calls and their specialist notes | `learning/propose.py` `draft` |
| Gate | Cluster, held-out, derived and test-suite cases on both arms; lift, no regression, no new hard fail, no slowdown | `learning/gate.py` |
| Review | The inbox; approve (or publish anyway with a note), edit, reject (snoozes the cluster) | `routes/insights.py` |
| Ship | A new version "Fix: …", derived scenarios join the suite, the suite runs on publish | `propose.approve` |

The guardrails hold: a run never publishes, approves or edits anything; held-out cases never reach the drafter; website pages are never edited; a rejected cluster is snoozed.

# Gaps

| # | Gap | Evidence | Effect |
|---|---|---|---|
| R14 | **Approval publishes the builder's draft plus the fix, not the version that was evaluated plus the fix** | `propose.approve` starts from `agent.draft_config`; the gate's candidate is `candidate_config(published config, proposal)` | Unreviewed draft edits ship under a "Fix: …" note, and the version that goes live was never gated |
| R15 | **A fixed cluster is never revisited** | Approval sets the cluster to `fixed`; new calls with the same gap still join it (`assign_cluster` skips only `ignored`), but readiness needs `open`. Nothing compares the cluster's signal rate before and after `resulting_version_id` | A fix that does not work in production goes silent. Seen in the demo: rerunning Act 6 on the same database stalls until the old cluster is ignored |
| R16 | **The gate is noisy** | Cluster cases run once; lift needs one more pass than the baseline; held-out cases come only from cluster members beyond the 10 shown to the drafter, so clusters of 5–10 calls have none and SL-08 is vacuous; the slowdown rule compares p95 over a few dozen simulated turns. On 2026-11-01 the same newborn fix was blocked in one fake run by "Slower: p95 329 ms against 72 ms" (fake mode, where the model takes no time) and passed in the next. In Act 6 the baseline passed 4 of 5 cluster cases (the fake judge accepts a confident unrelated answer), so the fix passed on a lift of exactly one | Good fixes are blocked and weak ones pass by one lucky replay; reviewers learn to "publish anyway" |
| R17 | **"No answer" from knowledge search almost never fires** | The no-answer rule is a similarity floor (0.60 local, 0.15 API embeddings). Against the SafeTrip agent, 9 of 10 questions the knowledge cannot answer (policy extensions, pets, pregnancy, cruises, strikes, missed connections) scored 0.62–0.76 and returned unrelated chunks; skiing paraphrases flipped between no answer and 0.70. Fake run: 0 `no_answer` signals among 9 calls | The agent receives irrelevant chunks and may answer from them; learning sees the gap only when the caller escalates or dislikes the call |
| R18 | **A draft may be grounded in the AI, not a human** | When an evidence call has no specialist note, the drafter's "Specialist:" line is the analysis's own `resolution_summary` (`cluster_evidence`); clusters built from quality signals (no escalation) never have a note | A knowledge article can be written from the model's own guess, then "proven" by a simulated caller that cannot tell a right answer from a confident one |
| R19 | **One readiness threshold for every agent and every severity** | 5 signals in 28 days, a global setting | A low-volume agent never learns; a recurring hard-gate failure waits like a missing FAQ |
| R20 | **Evaluation findings drive nothing** | Drift flags (SC-10), checks failing on many calls, test scenarios failing on the published version and uncalibrated judge fails are shown, not queued. A judge check counts as a signal only after 20 human reviews per agent (SC-09), which few checks will ever get | Evaluation is a report, not a to-do list; calibration never happens because nothing asks for reviews |

Already on the roadmap and still open: **R7** (a fix may need an article *and* a rule), **R8** (explain a failed gate and redraft), **R9** (realistic simulated callers: today the main reason live gates fail), **R10** (flaky scenario quarantine), **R3** (configuration root cause).

# The target loop

| Stage | Should | Fixes |
|---|---|---|
| 1. Detect | Signals as today, plus: the agent saying it has no approved answer, the `knowledge.admits_unknown` check failing, and a relevance check on search results (a reranker or a judge question "does any result answer this?") instead of a similarity floor | R17 |
| 2. Act on evaluation | Drift, a check failing on more than N % of a version's calls, and a test scenario failing on the live version each create an inbox item. "Review 10 calls of this check" is one of them, so calibration happens as a side effect | R20 |
| 3. Diagnose | Root causes as today plus `configuration` (setup alerts, not clusters) | R3 |
| 4. Get the truth | A knowledge fix needs a human answer. When a ready cluster has no specialist notes, the inbox shows **Answer needed**: "Callers ask *how to extend cover abroad*; what is the answer?" The reviewer's answer becomes the evidence; the AI's own summaries never do | R18 |
| 5. Ready | Per-agent threshold (default 5, lower for low-volume agents) and severity weighting: a hard-gate or safety failure is ready at 1–2 | R19 |
| 6. Draft | The smallest change, possibly a bundle (article + rule), against the **published** config | R7, R14 |
| 7. Prove | Cluster cases repeated (3×) and lift measured as a pass rate; at least one held-out case reserved even in small clusters (or a paraphrased scenario when there is none); flaky scenarios quarantined; latency compared on turns both arms answered, with a floor that ignores simulation noise; realistic simulated callers | R16, R10, R9 |
| 8. Decide | A person approves, with each failing replay explained and **Revise draft** sending failures back to the drafter | R8 |
| 9. Ship what was proven | Publish exactly *published config + fix*; if the draft has unpublished edits, say so and keep them as a draft on top of the new version | R14 |
| 10. Verify in production | For 14 days after a fix, compare the cluster's weekly signal rate with the 28 days before. Show "Fix held: escalations 6/week → 0/week". If new calls keep joining a fixed cluster, reopen it as **Fix did not hold** with the evidence, and offer a rollback to the previous version | R15 |
| 11. Learn about learning | Track proposals drafted, approved, rejected and forced; how often a passed gate was followed by "fix did not hold". These tell whether to trust the gate | R15, R16 |

# What the demo shows

| Act | Shows |
|---|---|
| 5 | Drafting and evaluating a fix from seeded history (newborn coverage); stops before approval |
| 6 | The whole loop on the agent built in Act 1: bad calls, the specialist's answers, **Run learning now**, the proposal and its gate, **Approve & publish**, the same question answered by the new version |

The automated run reports the gaps it meets as KNOWN (R15 on a rerun, R16 when the gate blocks) so they stay visible until fixed.

# Suggested order

1. **R14** (small, P0: ship what was proven) and **R15** (P0: verify in production, reopen).
2. **R18** (P0 for knowledge fixes in a health insurer: never learn facts from the AI).
3. **R9** then **R16** (the gate becomes trustworthy), then **R8**.
4. **R17**, **R20**, **R19**, **R7**.
