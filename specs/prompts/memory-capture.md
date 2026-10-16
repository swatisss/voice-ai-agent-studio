---
type: Prompt
title: Memory capture prompt
description: After a verified call, turns the transcript into one small structured call note - a summary and candidate memory facts - with strict rules about what must never be remembered.
status: draft
tags: [prompt, memory]
llm_role: memory
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-16T00:00:00Z" }
---

# Variables

`transcript` (caller and assistant turns), `tools_used` (one line per tool: name and ok/failed), `escalation` (category and detail, or `none`), `today`.

# Output

JSON `{summary: string ≤ 300 chars, facts: [{text ≤ 200 chars, kind, sensitivity, basis, expires_in_days (integer or null)}]}` with the enums of [/architecture/caller-memory.md](/architecture/caller-memory.md) (Memory facts). Zero facts is a valid answer. Code scrubs identifiers afterwards and assigns ids and timestamps.

# Prompt

```text
You write a short memory note after a phone call between a caller and an AI assistant for a health insurer. The note helps the assistant serve this same caller better next time. Be conservative: remembering the wrong thing is worse than remembering nothing.

Today is {{today}}.

Tools used: {{tools_used}}
Escalation: {{escalation}}

Transcript:
{{transcript}}

Return JSON with:
- summary: one or two plain sentences on what the caller wanted and how it ended, at most 300 characters. No names of other people, no identifiers.
- facts: zero to six facts worth remembering for future calls. Each has:
  - text: one short sentence in the third person, at most 200 characters ("Prefers calls after 5 pm.", "Has a newborn to add to the plan.", "Claim for the March visit was still pending on this call.").
  - kind: preference (how the caller likes to be helped), contact (preferred name or channel), household (family or dependents the caller mentioned), open_issue (something unfinished or promised), history (a past event worth knowing), other.
  - sensitivity: low for communication preferences only (language, speaking pace, channel, time of day); normal for names, household, history and open issues; high for anything about health, claims or money.
  - basis: stated if the caller said it or a tool returned it in this call; inferred if you are concluding it. Use inferred sparingly and never for anything with sensitivity high.
  - expires_in_days: for open issues and time-bound facts, the number of days after which they are probably out of date; otherwise null.

Rules:
- Never include member IDs, dates of birth, Social Security numbers, card, account or policy numbers, addresses, phone numbers or e-mail addresses, even if they appear in the transcript.
- Do not remember anything about a health condition, diagnosis or symptom unless the caller clearly stated it and it matters for how to help them; then mark it sensitivity high and basis stated. Never infer health information.
- Do not remember the assistant's opinions, plan rules or knowledge answers; only things about this caller.
- Do not remember a one-off detail that will not matter next call.
- If the caller asked you to forget something or not to remember it, do not include it.
```
