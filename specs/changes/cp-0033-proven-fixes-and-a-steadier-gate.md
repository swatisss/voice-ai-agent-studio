---
type: Change Proposal
title: CP-0033 Ship what was proven, and a steadier gate
description: Approving a fix publishes the published version plus the fix (exactly what was gated) and keeps unpublished draft edits as a draft; the gate repeats cluster cases, measures lift as a pass rate, always keeps a held-out case and blocks on latency only past the agent's budget.
status: stable
cp_state: implemented
tags: [learning, evaluation]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-01T00:00:00Z" }
---

# Why

From the self-learning review ([How self-learning should work](/architecture/self-learning-target.md), roadmap R14, R16):

* **What is published is not what was gated (R14).** The gate's candidate is *published config + fix*; approval publishes *builder's draft + fix*. Unreviewed edits ship under "Fix: …".
* **The gate is noisy (R16).** On 2026-11-01 the same fix was blocked in one fake run by "Slower: p95 329 ms against 72 ms" and passed in the next; Act 6 was blocked by "p95 264 ms against 36 ms" and passed the run before. Cluster cases run once and one extra pass is enough lift. Clusters of 3–10 calls have no held-out case at all, because all of them are shown to the drafter.

# What changes

1. **Approval publishes the gated config.** The new version is the published version's config with the change applied. If the builder's draft differed from the published version, it keeps its edits plus the change and stays unpublished; the response says so (`draft_kept: true`) and the success banner tells the reviewer.
2. **Held-out cases in every cluster of 3 or more.** The drafter is shown at most `n − max(1, ⌊n / 5⌋)` of a cluster's `n` member calls (at most 10, as today); the rest (at most 4) are held out.
3. **Cluster and held-out cases repeat** `learning.case_repeats` times (default 2, 1–5).
4. **Lift is a pass rate.** The candidate's pass rate over cluster and held-out runs must exceed the baseline's by at least 25 points, and the candidate must pass at least half of the held-out runs when there are any.
5. **Latency blocks only past the budget.** A slowdown (p95 more than 1.2× and 200 ms above the baseline) blocks the gate only when the candidate's p95 is also above the agent's `evaluation.latency_p95_ms`; otherwise it is a **warning** shown with the gate.

# Affected specs

* [/architecture/self-learning.md](/architecture/self-learning.md) - Gate (case repeats, lift, latency, warnings), held-out reserve, Review (approval publishes the gated config); SL-08, SL-10 unchanged; SL-17…SL-20
* [/architecture/evaluation.md](/architecture/evaluation.md) - repeats per case type, summary `warnings`
* [/architecture/fleet-learning.md](/architecture/fleet-learning.md) - approval applies to the published config
* [/data/agent-config.md](/data/agent-config.md) - `learning.case_repeats`
* [/api/rest-api.md](/api/rest-api.md) - approve returns `draft_kept`
* [/ui/insights.md](/ui/insights.md) - gate warnings; banner when the draft was kept
* [/product/roadmap.md](/product/roadmap.md) - R14, R16 → CP-0033

# Acceptance criteria

Defined in the specs above: **SL-17…SL-20**.

# Tasks

1. Spec edits (this CP).
2. `propose.approve` from the published config — SL-17.
3. Held-out reserve in `propose.draft`; repeats and the new rules in `gate.py` — SL-18, SL-19, SL-20.
4. Web: warnings and the draft-kept banner.
5. Tests; the demo's fake judge stops accepting answers that share one word with the goal, so lift is measured honestly.

# Risks and rollout

Repeating cluster cases doubles their simulated calls (live: about 10 more per proposal). Existing proposals keep their gate result; re-evaluating applies the new rules.

# Out of scope

Realistic simulated callers (R9), flaky scenario quarantine (R10), bundled fixes (R7), redrafting from gate failures (R8).
