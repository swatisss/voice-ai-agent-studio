---
type: Product Brief
title: Product vision
description: A multi-tenant voice AI agent platform that resolves routine calls, escalates hard ones with full context, and learns from every escalation.
status: stable
tags: [product, vision]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Problem

Business units that want phone-based support either overload human agents with repetitive, low-complexity calls, or spend months building a one-off voice bot that never improves after launch. A human-handled support interaction costs roughly **$7–12**; an AI-resolved voice interaction costs **under $1.20**. Teams lack a scalable, safe way to capture that gap without hurting customer experience.

# Product

A multi-tenant voice AI platform. Any business unit (a **tenant**) onboards in minutes by providing three things:

1. **Knowledge** — documents, FAQs, policies ([/architecture/knowledge.md](/architecture/knowledge.md)).
2. **Skills** — callable tools (APIs) and the plain-English procedures that use them ([/architecture/tools-and-skills.md](/architecture/tools-and-skills.md)).
3. **Persona** — name, voice, tone, disclosures and escalation policy ([/data/agent-config.md](/data/agent-config.md)).

It instantly gets a voice agent that:

1. **Resolves** routine calls end-to-end with no human involved.
2. **Escalates** hard, ambiguous or high-risk cases to a human with a **groundwork packet** — summary, detected intent, what was already tried, sentiment, suggested next step — so the human never starts from zero ([/architecture/escalation.md](/architecture/escalation.md)).
3. **Learns** from its failures. A background **fleet learning** layer analyzes every call, clusters recurring gaps (missing knowledge, missing skills), drafts fixes, proves them by replaying real cases with simulated callers, and ships them after human approval ([/architecture/fleet-learning.md](/architecture/fleet-learning.md)).

# Demo domain

**Evergreen Health**, a fictional health and motor insurer. The business unit *Customer Support & Channels* runs seven use cases: Policy Inquiry & Status, Claims Status Tracking, Document Center & Green Card, Outbound Renewal Calls, Policyholder Onboarding, an Internal Knowledge Assistant for staff, and Coverage Information Support ([/product/use-cases.md](/product/use-cases.md)). A second, empty *sandbox* business unit shows isolation. All data is synthetic. See [/demo-data/evergreen-health.md](/demo-data/evergreen-health.md).

# Business impact

* **Lower cost** — absorb high-volume, low-complexity calls.
* **Better human SLA** — humans inherit a warm, context-rich handoff instead of an angry caller starting over.
* **Horizontal scale** — one platform, any team, self-service onboarding.
* **Compounding improvement** — containment rises week over week because recurring escalations become approved fixes.

# Success metrics

| Metric | Definition |
|---|---|
| Containment rate | resolved ÷ (resolved + escalated) calls |
| Escalation precision | escalations whose root cause is `policy_required`, `safety` or `caller_requested` ÷ all escalations |
| Cost saved | resolved calls × (human cost − AI cost); defaults $9.50 and $1.20 |
| Fix lift | candidate pass rate − baseline pass rate in an eval run |
| Response latency | p50/p95 time from end of caller speech to first agent audio |
