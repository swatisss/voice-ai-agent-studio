---
type: Decision Record
title: ADR-0011 Evaluation and self-learning for declarative agents
description: One scorer shared by online scoring of every call, offline test suites and a nightly self-learning loop; checks come from the agent's own config; improvements are typed config changes that only a human publishes. Records the research behind the plan and its three change proposals.
status: stable
tags: [decision, evaluation, learning, compliance]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-31T00:00:00Z" }
---

# Context

Studio agents are declarative: an agent is a config (persona, policy rules, `escalate_when`, `never`, tools, skills, knowledge docs, memory rules, voice settings) frozen into an immutable [agent version](/data/agent-config.md) on publish, and every call records the version that handled it. Builders want to know how each agent performs across its knowledge, tools and memory, and want agents to improve from their own calls without ever changing themselves.

What existed on 2026-10-31: [evaluation](/architecture/evaluation.md) (LLM simulated caller, LLM judge with `outcome / goal_met / grounded / policy_violations`) runs only to gate a fix proposal; [fleet learning](/architecture/fleet-learning.md) analyses and clusters escalated and thumbs-down calls and drafts knowledge, skill or policy fixes a human approves; nothing scores production calls, nothing runs on a schedule except the memory purge.

Research (2026-10-31, primary sources; full notes kept outside the bundle):

* Voice-agent eval vendors converge on one loop: a simulated caller (scenario + persona) against the real agent, an LLM judge on binary or labelled criteria, repeated runs reported as a pass rate, sampled scoring of production calls, failed calls turned into regression tests. https://docs.livekit.io/testing/simulations · https://elevenlabs.io/docs/eleven-agents/customization/agent-testing · https://docs.vapi.ai/observability/evals-quickstart · https://docs.retellai.com/test/llm-simulation-testing
* Metric catalogues: Roark (system metrics incl. tool-call parameters and order, compliance) https://docs.roark.ai/documentation/metrics/system-metrics ; Cekura (latency percentiles, interruptions, CSAT) https://docs.cekura.ai/documentation/key-concepts/metrics/pre-defined-metrics ; Retell per-call e2e latency p50/p90/p95/p99 https://docs.retellai.com/api-references/get-call
* Reliability: τ-bench pass^k, "the chance that all k i.i.d. trials are successful"; τ²-bench grades mostly in code from the final database state. https://arxiv.org/abs/2406.12045 · https://arxiv.org/abs/2506.07982
* Judge design: binary verdicts, one question per criterion, an "unknown" answer, calibration against human labels (agreement read with catch rate and the constant-answer baseline). https://elevenlabs.io/docs/agents-platform/customization/agent-analysis/success-evaluation · https://docs.coval.ai/guides/improving-your-llm-judge
* RAG and tool metrics: Ragas faithfulness, context precision/recall, tool-call F1; DeepEval tool and argument correctness. https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/ · https://deepeval.com/docs/metrics-tool-correctness
* Healthcare: 45 CFR 164.514(h) requires verifying identity before disclosing PHI; vendors test it with adversarial callers. Under HIPAA modes, Vapi and ElevenLabs keep analysis of PHI calls inside the BAA boundary. https://www.law.cornell.edu/cfr/text/45/164.514 · https://docs.vapi.ai/security-and-privacy/hipaa
* Self-learning: learn from external signals (ExpeL, Agent Workflow Memory, Reflexion); self-correction without one is unreliable (Huang et al. 2023). Risks: overfitting to the eval set, proxy over-optimisation, feedback loops. https://arxiv.org/abs/2308.10144 · https://arxiv.org/abs/2409.07429 · https://arxiv.org/abs/2310.01798
* OpenAI's hosted Evals platform is being retired (read-only 2026-10-31, shut down 2026-11-30); not a dependency.

# Options

1. **Adopt an external eval vendor** — fast, but sends PHI transcripts to another processor and does not know our declarative config.
2. **Separate systems per loop** (a production scorer, a test runner, a learning job) — three judges to calibrate, scores not comparable.
3. **One scorer, three loops, checks derived from the config** — the same scorecard for production calls, simulations and candidate changes.

# Decision

Option 3.

1. **The unit of evaluation is an agent version.** Every scorecard and run is tied to one; versions are compared directly.
2. **Checks come from the declarative config**, so a builder writing a rule gets its check for free: each `policy.never` item is a hard-gate check, each `escalate_when` (policy and skills) a missed-escalation check, verification and `requires_verification` tools give the PHI-before-verification check, tools and knowledge give tool-use and groundedness checks, memory settings give memory checks. Built-in healthcare checks and up to ten custom judge checks per agent complete the list.
3. **Code first, judge second.** Whatever the event log can decide (latency, tool errors, verification order, end state) is checked in code; the judge answers one binary question per check (`pass`, `fail`, `n/a`, `unknown`) and cites evidence. Safety and compliance checks are **hard gates**.
4. **Judges earn trust.** Reviewers agree or disagree with each verdict; agreement per check is reported, and a check with fewer than 20 reviews or under 85 % agreement is *uncalibrated* and gates nothing.
5. **Three loops, one scorer:**
   * **Online** — every ended real call gets a scorecard; code checks always, judge checks on a sample (always on escalated, thumbs-down and hard-failed calls); daily rollups per version; drift flags.
   * **Offline** — editable test suites per agent: scenarios with persona, profile, expected outcome, required and forbidden tools, expected end state and optional memory precondition; each run k = 3 times (pass^3) against the published version, the draft or a candidate change.
   * **Self-learning** — a nightly job gathers external signals (failed checks, escalations, thumbs-down, tool errors, no-answer searches), clusters them, drafts **typed config changes** (knowledge article or edit, skill and tool, tool attach, policy rule, memory rule, new scenario), derives regression scenarios that fail on the current version, gates each candidate offline on cluster, held-out and regression cases, and queues the passing ones for morning review.
6. **Agents never change themselves.** The runtime has no write path to config; only a human approving a change creates a version. Rollback is re-publishing an earlier version. Agent-written memory and knowledge are never fed back to the judge or simulator.
7. **Scoring stays inside our boundary**: same providers and posture as the call itself.

# Consequences

Delivered as three change proposals:

| CP | Scope |
|---|---|
| [CP-0020](/changes/cp-0020-call-scoring-and-online-evaluation.md) | Scoring core and online evaluation: check catalogue derived from the version, scorecards, the judge's check list, structured knowledge retrievals, `score_call`, rollups and drift, reviews and calibration, the Evaluation page, the builder's Evaluation tab |
| CP-0021 (planned) | Test suites: eval runs decoupled from proposals, editable scenarios with expectations and memory preconditions, k runs and pass^k, runs on any version or the draft, **Run tests** in the builder (report only) |
| CP-0022 (planned) | Self-learning: nightly scheduler, signal gathering, new proposal kinds, held-out gating, a learning inbox; gating publish on test results |

* Insights keeps clusters and proposals ("what is going wrong, what fix is proposed"); Evaluation answers "how good is each agent, measured".
* Out of reach in text simulation: WER, voice quality, audio-level noise and accents; realtime agents keep the `text_approximation` label.
* Judge cost grows with call volume; the per-agent sample rate bounds it.
