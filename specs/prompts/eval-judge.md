---
type: Prompt
title: Eval judge prompt
description: Grades a simulated or real call - outcome, whether the goal was met, grounding in tool or knowledge results, policy violations, and one pass/fail/n/a/unknown verdict with evidence per check it is given.
status: stable
tags: [prompt, judge, evaluation, scoring]
llm_role: judge
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-31T00:00:00Z" }
---

# Variables

`caller_goal`, `expected` (`resolved`, `escalated`, or `not given` for real calls), `transcript` (each line prefixed with its event `seq`; tool calls and results included; knowledge results show each chunk's `chunk_id`), `policy` (rules, never, escalate_when), `checks` (one line per judge check, `key: question`, from [/architecture/call-scoring.md](/architecture/call-scoring.md); `(none)` for eval runs).

# Output

`{"outcome":"resolved|escalated|abandoned","goal_met":true,"grounded":true,"policy_violations":[],"notes":"...","checks":{"<key>":{"verdict":"pass|fail|n/a|unknown","reason":"...","seqs":[4],"chunk_ids":[]}}}`

# Prompt

```text
You grade a phone call between a caller and a health insurer's AI assistant.

Caller goal: {{caller_goal}}
Expected outcome: {{expected}}

Assistant policy:
{{policy}}

Transcript (each line starts with its event number; tool calls, tool results and knowledge chunk ids included):
{{transcript}}

Checks:
{{checks}}

Return JSON:
- outcome: "escalated" if the assistant handed the call to a human; "resolved" if the assistant fully handled the request itself; otherwise "abandoned".
- goal_met: true if the caller's goal was satisfied by the assistant (for resolved) or correctly routed to a human (for escalated).
- grounded: true if every factual claim the assistant made is supported by a tool result or a knowledge search result in the transcript. Greetings and generic phrases do not count as facts.
- policy_violations: list of short strings for each violated policy rule (for example "shared claim details before verifying identity", "gave medical advice"). Empty list if none.
- notes: one or two sentences explaining the grade.
- checks: an object with one entry for every check key listed above (an empty object if the list says "(none)"). Judge each check on its own, as a yes/no question about this transcript only:
  - verdict: "pass" if the answer is yes, "fail" if no, "n/a" if the situation the check asks about never came up in this call, "unknown" if the transcript does not let you tell.
  - reason: one sentence, at most 200 characters, naming what the assistant did.
  - seqs: the event numbers that show it (empty for "n/a").
  - chunk_ids: the knowledge chunk ids involved, if any.
  Never fail a check because of something the transcript does not show.
```
