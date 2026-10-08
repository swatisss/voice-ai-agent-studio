---
type: Component Spec
title: Fleet learning
description: Post-call analysis, gap clustering, impact estimation, fix drafting from human resolutions, and approval into a new agent version.
status: stable
tags: [architecture, learning, clustering]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# 1. Call analysis (`analyze_call` job)

Input: transcript, tool events, escalation (category, packet, disposition, resolution note if already resolved), and the caller's feedback if any (thumbs up or down and comment, [/architecture/call-ending-and-feedback.md](/architecture/call-ending-and-feedback.md)). Prompt: [/prompts/call-analysis.md](/prompts/call-analysis.md), role `analysis`.

Output stored in `call_analyses`:

| Field | Values |
|---|---|
| `outcome` | `resolved` · `escalated` · `abandoned` |
| `intent` | snake_case, e.g. `claim_status`, `add_dependent_newborn` |
| `root_cause` | `none` (resolved and not thumbs-down) · `missing_knowledge` · `missing_skill` · `tool_error` · `policy_required` · `safety` · `caller_requested` · `asr_error` · `agent_error` · `other` |
| `fixable` | true iff root cause ∈ {`missing_knowledge`, `missing_skill`, `agent_error`} |
| `gap_summary` | One sentence naming what was missing, phrased generically ("How to add a newborn to an existing plan"); empty when resolved without a thumbs down. For a thumbs-down call it names what the caller was probably unhappy about (using their comment) and is never empty |
| `caller_goal` | One sentence goal usable by a simulated caller |
| `resolution_summary` | What resolved it (agent answer or human note), may be empty |
| `sentiment_start`, `sentiment_end` | as in the packet |

The call's `outcome` column is set from the analysis. If the escalation is resolved **after** analysis ran, analysis re-runs once (`analyze_call` re-queued by the resolve endpoint) to capture the human note. Likewise a **thumbs down** re-queues `analyze_call` once (dedupe key `analyze_call:{call_id}:feedback`) so the analysis sees the feedback; a thumbs up queues nothing. The `outcome` is unchanged by feedback: a resolved call the caller disliked stays `resolved` (containment is not affected) but becomes a learning candidate.

# 2. Clustering

Only analyses with a non-empty `gap_summary` are clustered, and only if the call's outcome is `escalated` **or** its caller gave a thumbs down. Clusters are per agent.

1. Embed `gap_summary` (same provider as knowledge).
2. Find the cluster (same agent, status ≠ `ignored`) with highest cosine similarity between its centroid and the embedding.
3. If similarity ≥ `FL_CLUSTER_THRESHOLD` (default **0.80** fastembed / 0.35 hash) → join it; update centroid as the running mean (re-normalized).
4. Else create a cluster; name and description come from [/prompts/cluster-naming.md](/prompts/cluster-naming.md) (role `drafting`) using up to 5 member gap summaries; `root_cause` = majority root cause of members.
5. Recompute cluster stats: `call_count`, `escalation_count`, `first_seen`, `last_seen`, `fixable` (majority).

Seeded history creates clusters directly from its `cluster_key` (deterministic demo) and computes centroids from member embeddings ([/demo-data/call-history.md](/demo-data/call-history.md)).

# 3. Impact and readiness

* `weekly_escalations` = escalations in the last 28 days ÷ 4.
* `est_weekly_cost_usd` = `weekly_escalations` × (`HUMAN_COST_PER_CALL` 9.50 − `AI_COST_PER_CALL` 1.20).
* `dislike_count` = member calls with a thumbs down in the last 28 days; `signal_count` = distinct member calls in that window that were escalated **or** thumbs-down (a call that is both counts once).
* A cluster is **ready for a fix** when `fixable` and `signal_count` ≥ `FL_MIN_CLUSTER_SIZE` (default 5) and no open proposal exists. "Watching (n of 5)" shows `signal_count`.
* The dashboard's escalation root-cause chart and `weekly_escalations` still count escalations only; thumbs-down resolved calls appear in neither.
* Non-fixable clusters show the label **"Correct escalation — no fix"** (policy, safety, caller-requested) or **"Investigate"** (tool_error, asr_error, other).

# 4. Fix drafting (`draft_fix` job, triggered by the Insights UI)

Prompt [/prompts/fix-draft.md](/prompts/fix-draft.md), role `drafting`. Evidence: up to 10 member calls — gap summaries, caller goals, and **human resolution notes** (the ground truth of what a human told the caller). Output `kind`:

| Kind | When | Payload |
|---|---|---|
| `knowledge_article` | `missing_knowledge` | `{title, content_markdown}` — becomes a `knowledge_docs` row with status `draft` |
| `skill` | `missing_skill` | `{skill: {name, description, instructions, required_tools, escalate_when}, tool: <tool def or null>, existing_tool_name: <name or null>}` — tool drafts may only target endpoints listed in the tenant's tool catalog ([/demo-data/evergreen-health.md](/demo-data/evergreen-health.md)) |
| `policy_rule` | `agent_error` | `{rule: "one sentence added to policy.rules"}` |

Proposal status: `draft` → `evaluating` → `ready` (eval done) → `approved` | `rejected`. Editing the draft payload in the UI is allowed in `draft`/`ready`; any edit returns it to `draft` (needs re-evaluation).

# 5. Approval (`POST /api/proposals/{id}/approve`)

Allowed only in `ready` with an eval run whose candidate pass rate ≥ baseline pass rate and **no regression failures** (unless `force: true` with a note).

1. Apply the payload to the agent draft config: activate the draft doc and add it to `knowledge_doc_ids`; or create the skill (and tool) and attach; or append the policy rule.
2. Publish a new agent version with `change_note` = "Fix: {proposal title}" and `source_proposal_id`.
3. Proposal → `approved` with `resulting_version_id`; cluster → `fixed`.
4. Publish `proposal.approved` and `agent.published` events.

# Acceptance

- **FL-01** — Given an ended call, when `analyze_call` completes, then exactly one `call_analyses` row exists and the call outcome matches it.
- **FL-02** — Given two escalated analyses with near-identical gap summaries, when clustered, then they join the same cluster.
- **FL-03** — Given an analysis whose best similarity is below threshold, when clustered, then a new cluster is created with an LLM-generated name.
- **FL-04** — Given a cluster whose majority root cause is `policy_required`, then it is not fixable and shows "Correct escalation — no fix".
- **FL-05** — Given a ready cluster with resolution notes, when `draft_fix` runs for `missing_knowledge`, then a proposal with kind `knowledge_article` and a `draft` doc are created.
- **FL-06** — Given a proposal whose eval has a regression failure, when approved without `force`, then the API returns 409.
- **FL-07** — Given an approved knowledge proposal, then a new agent version exists whose config lists the (now active) doc, and the cluster status is `fixed`.
- **FL-08** — Given an escalation resolved after its call was analyzed, when resolved, then the call is re-analyzed once and the analysis includes the resolution summary.
