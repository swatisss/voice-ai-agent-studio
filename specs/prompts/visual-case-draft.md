---
type: Prompt
title: Visual case draft prompt
description: "Turns pinned observations and the transcript into the case narrative, the list of what is still missing, and a routing decision with a reason."
status: draft
tags: [prompt, evidence, cases]
llm_role: drafting
generated: { by: "claude-code/claude-opus-5", at: "2026-10-12T00:00:00Z" }
---

# Variables

`kind` (`facility_fault` or `claim`), `observations` (the pinned evidence in order, each with `description`, `items`, `confidence`, `asked_for` and `source`), `transcript` (the call so far), `caller_verified` (boolean), `entities` (what the call established: member reference, policy id, location, asset id — any may be absent).

# Output

```json
{
  "narrative": "Staff reported a bent side rail on a ward bed. A captured frame shows the rail bent outward near its hinge with the end cap missing. The ward was not stated on the call.",
  "missing": ["Ward and bed number", "A photograph of the hinge from closer in"],
  "routing": "needs_docs",
  "routing_reason": "The fault is confirmed but the bed cannot be located from what the call established.",
  "sample_evidence": false
}
```

# Prompt

```text
You are drafting an intake case for a human reviewer from a call that is ending. The case kind is {{kind}}.

Pinned observations, in the order the agent looked:
{{observations}}

Call transcript:
{{transcript}}

Caller identity verified: {{caller_verified}}
Established details: {{entities}}

Write narrative in three to five sentences for someone who did not hear the call. State only what the observations support and what the call established. An observation with confidence unclear or not_confirmed must be reported as such, not smoothed over — if the caller described something the frames did not show, the narrative says what was seen instead. Never write the caller's characterisation as fact. Do not state a cause, a cost, a fault, or a coverage decision.

List in missing everything a reviewer would need and does not have: a location, an asset or policy identifier, a document, a better photograph (use the asked_for text when one is present). Each entry is one short phrase. An empty list is correct when nothing is outstanding.

Choose routing:
- needs_docs: something in missing has to arrive before anyone can decide.
- ready_for_review: a reviewer has what they need to decide now.
- siu_review: the account of what happened and what the frames show do not fit together, or the claim's circumstances need a specialist look before it is paid.
- escalate: a person is needed on this call or immediately after it.

Give one sentence in routing_reason. Write it for the reviewer, not for the caller — it is never read out.

Set sample_evidence to true when every observation has source "sample".

Return JSON with exactly the fields narrative, missing, routing, routing_reason and sample_evidence.
```
