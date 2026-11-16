---
type: Change Proposal
title: CP-0045 A small seeded call history (20 calls)
description: The seed creates 20 recent calls instead of 123, so the dashboard shows a believable handful and the owner can build on top of it; agents, knowledge and members stay, and the newborn gap still reaches Ready for fix.
status: stable
cp_state: implemented
tags: [seed, demo-data, dashboard]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-16T00:00:00Z" }
---

# Why

The owner does not want "123 calls" of synthetic history in the database: the dashboard should show only 10-20 calls as an overall view, and the product will be built up from there. Agents, knowledge, members and scenarios stay.

The seeded calls also feed the self-learning demo (Insights clusters, Draft fix) and the Evaluation page, so shrinking them must keep those working or say plainly what goes away.

# What changes

* [Call history](/demo-data/call-history.md) seeds **20 calls** over the same 28-day window (weekly 4, 5, 5, 6): 10 resolved, 9 escalated, 1 abandoned (containment 50%).
  * Resolved: 2 `policy_status`, 3 `payment_question`, 2 `document_request`, 2 `coverage_question` (one policy cover, one cash plan), 1 `gp_booking`.
  * Escalated: 5 `add_dependent_newborn` (`newborn`, spread 1, 1, 1, 2), 3 `prior_auth_status` (`prior_auth`), 1 `complaint` (`complaints`).
  * `cancellation` and `speak_to_person` are no longer seeded, so those two clusters do not exist in a fresh database (they appear when real calls create them).
* **No threshold change.** `FL_MIN_CLUSTER_SIZE` stays 5. *Adding a newborn to the policy* (5 signals) is **Ready for fix**; *Pre-authorisation status* (3) shows **Watching (3 of 5)**, which is a better picture of the two states; *Complaints* (1) stays a correct escalation. The demo's Act 6 draws on newborn only.
* `knowledge.grounded` fails on 1 seeded call (the latest resolved coverage call) instead of 5; `outcome.goal_met` fails on the 1 abandoned call.
* **Drift is no longer flagged on the seeded version**: drift needs at least 20 scored calls in both the first and last 7 days ([call scoring](/architecture/call-scoring.md)), which 20 calls cannot reach. The rule itself is unchanged (SC-10 still tests it). The Evaluation Drift badge and the nightly "drift" action finding therefore do not appear for seed alone; they appear once real volume exists.
* Demo script, walkthrough and demo guide quote the new numbers.

# Affected specs

* [/demo-data/call-history.md](/demo-data/call-history.md) - 20-call mix, weekly volumes, grounded failure, UC-05 counts.
* [/architecture/call-scoring.md](/architecture/call-scoring.md) - SC-12 counts; no drift flag on the seed.
* [/ui/evaluation.md](/ui/evaluation.md) - UI-47 without the Drift badge, one failed grounded call.
* [/product/demo-script.md](/product/demo-script.md), [/product/demo-walkthrough.md](/product/demo-walkthrough.md) - counts, ready/watching clusters, evidence count.
* [/demo-data/index.md](/demo-data/index.md) - description.

# Acceptance criteria

* **UC-05** (changed) — see [call history](/demo-data/call-history.md): the summary counts 20 calls (10 resolved, 9 escalated, 1 abandoned); *Adding a newborn to the policy* (5) is ready for a fix, *Pre-authorisation status* (3) is watching, *Complaints* is a correct escalation.
* **SC-12** (changed) — 20 scored calls, `goal_met` fails on exactly 1, `grounded` on exactly 1, no drift.
* **UI-47** (changed) — one failed Grounded call, no Drift badge.
* No new IDs.

# Tasks

1. Spec edits (done in this CP).
2. `seed/history.py`: new `MIX`, `WEEKLY`, `NEWBORN_WEEKLY`; docstring; drop the `cancellation` and `speak_to_person` templates only if unused elsewhere (keep the helpers). `seed/loader.py`: `_ungrounded` picks the latest resolved coverage call. — covers UC-05, SC-12
3. Tests: `test_deploy_and_dashboard.py`, `test_use_cases.py` (20/10/9/1), `test_learning.py` (20), `test_call_scoring.py` (20 scored, no drift), `test_self_learning.py` (1 ready cluster, evidence 5, drafter sees all five), `test_agents_tenancy.py` (`members == 123` is not the call count; check before touching). Check the Draft fix hold-out and the 6-case evaluation still work with 5 evidence calls; if not, stop and ask. — covers UC-05, SC-12, UI-47
4. `scripts/demo_walkthrough.py` (`--learning` expectations), `docs/demo-guide.md`, `README` if it quotes counts.
5. Existing databases: `voiceai seed --reset` is how the owner gets the small set; no migration.

# Risks and rollout

* Resolved while implementing: with 5 newborn calls the drafter sees 4 and 1 is held out, so Draft fix, the held-out cases and the evaluation all still run. The seed's first day of the window is now left empty, because a call early on that day fell outside the 28-day impact window and the cluster stayed at 4 signals.
* Evaluation baseline/candidate numbers ("0/6 → 5/6") assumed 14 cluster calls; with 5 they will be smaller. Task 3 checks and the demo script is updated to the observed numbers.
* The fixed 28-day window means all 20 calls are recent; fine for the demo.
* Real calls placed in the playground sit on top of the seed; the dashboard "Include seeded history" toggle still separates them.

# Out of scope

* Deleting calls from an existing database in place (use `seed --reset`).
* Lowering `FL_MIN_CLUSTER_SIZE`, changing drift rules or the scoring model.
* Agents, knowledge, members, scenarios, personas.
