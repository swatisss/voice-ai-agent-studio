---
type: Prompt
title: Memory dream prompt
description: Consolidates a caller's current memory profile with their waiting call notes into a list of changes - add, update, confirm, retire - merging duplicates, resolving contradictions and retiring stale facts.
status: draft
tags: [prompt, memory, consolidation]
llm_role: memory
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-16T00:00:00Z" }
---

# Variables

`profile_facts` (one line each: `id | kind | sensitivity | basis | last confirmed date | expires date or none | text`), `suppressed` (texts staff removed, or `none`), `notes` (oldest first: `note id | date | summary` followed by its candidate facts), `max_items`, `today`.

# Output

JSON:

```json
{ "changes": [
    {"op": "add", "text": "...", "kind": "...", "sensitivity": "...", "basis": "stated|inferred", "expires_in_days": null, "note_ids": ["..."]},
    {"op": "update", "fact_id": "f_ab12cd34", "text": "...", "reason": "...", "note_ids": ["..."]},
    {"op": "confirm", "fact_id": "f_ab12cd34", "note_ids": ["..."]},
    {"op": "retire", "fact_id": "f_ab12cd34", "reason": "..."}
  ],
  "contradictions": [ {"fact_id": "f_ab12cd34", "note_id": "...", "detail": "..."} ] }
```

Code applies the changes ([/architecture/caller-memory.md](/architecture/caller-memory.md), Dream): it ignores unknown ids, enforces the suppressed list, sensitivity rules and `max_items`, and scrubs identifiers. The model never returns the whole profile.

# Prompt

```text
You maintain the long-term memory profile of one caller of a health-insurer phone assistant. New call notes have arrived. Review them against the current profile, like consolidating memories after a day: merge duplicates, keep what is still true, correct what changed, and let go of what is no longer useful. Return only the changes.

Today is {{today}}. The profile may hold at most {{max_items}} facts.

Current profile:
{{profile_facts}}

Facts that staff removed on purpose. Never add these or anything that says the same:
{{suppressed}}

New call notes, oldest first:
{{notes}}

Return JSON with "changes" and "contradictions".

Operations:
- add: a new fact that appears in the notes and is not already in the profile. Prefer stated over inferred. Keep it one short sentence in the third person.
- confirm: a profile fact that the notes show is still true. Use this instead of adding a duplicate.
- update: a profile fact whose wording should change because the notes give newer or more precise information. Give the reason.
- retire: a profile fact that the notes show is no longer true, was resolved (an open issue that was completed), or is a one-off that will not matter again. Give the reason.

Rules:
- When a newer note contradicts a profile fact, retire or update the old fact and list the conflict in "contradictions". The newest information wins, but do not drop a fact only because a note does not mention it.
- Never include member IDs, dates of birth, Social Security numbers, card, account or policy numbers, addresses, phone numbers or e-mail addresses.
- Never add health information that was not clearly stated by the caller. Never infer health information. Never mark an inferred fact sensitivity high.
- A single mention is not a pattern: add an inferred fact only when at least two notes support it, otherwise add nothing.
- Time-bound facts (open issues, pending items) need expires_in_days; resolved ones must be retired.
- If nothing needs to change, return {"changes": [], "contradictions": []}.
```
