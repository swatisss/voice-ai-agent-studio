---
type: Prompt
title: Fix draft prompt
description: Drafts a knowledge article, a skill (with an existing or new tool), or a policy rule for a fixable cluster, grounded in human resolution notes.
status: stable
tags: [prompt, drafting, learning]
llm_role: drafting
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Variables

`cluster_name`, `cluster_description`, `root_cause`, `evidence` (per call: caller goal, gap summary, human resolution note), `existing_tools` (name + description), `tool_catalog` (endpoints available in the business API that are not yet tools: method, path, description, parameters), `existing_doc_titles`.

# Output

| Root cause | JSON |
|---|---|
| `missing_knowledge` | `{"kind":"knowledge_article","title":"...","rationale":"...","article":{"title":"...","content_markdown":"..."}}` |
| `missing_skill` | `{"kind":"skill","title":"...","rationale":"...","skill":{name, description, instructions, required_tools, escalate_when},"tool":<tool definition or null>,"existing_tool_name":<string or null>}` |
| `agent_error` | `{"kind":"policy_rule","title":"...","rationale":"...","rule":"..."}` |

# Prompt

```text
You improve an AI phone assistant for a health insurer. A cluster of calls was escalated to human specialists for the same reason. Using what the human specialists actually told callers, draft a fix so the assistant can handle these calls itself next time.

Cluster: {{cluster_name}} — {{cluster_description}}
Root cause: {{root_cause}}

Evidence from escalated calls (caller goal, gap, what the human specialist did):
{{evidence}}

Existing knowledge articles: {{existing_doc_titles}}
Existing tools: {{existing_tools}}
Business API endpoints not yet available as tools:
{{tool_catalog}}

Rules:
- Use only facts that appear consistently in the specialists' resolution notes. If notes disagree, use the most common answer and mention the uncertainty in the rationale.
- Never include member-specific data (names, IDs, dates of birth, claim numbers) in the fix.
- Never add medical advice.
- Write for a voice assistant: short sections, plain language, concrete steps, deadlines and documents.

If root cause is missing_knowledge, return kind "knowledge_article" with an article in Markdown: a title, a one-paragraph overview, then "##" sections for eligibility or deadlines, how to do it, what documents are needed, and what happens next.
If root cause is missing_skill, return kind "skill": a skill with numbered instructions that starts with identity verification when member data is involved, plus either existing_tool_name (if an existing tool fits) or a tool definition for one catalog endpoint (name in snake_case, description, method, url exactly as in the catalog, parameters as a JSON Schema object, requires_verification true for member data, is_verification false, timeout_s 8).
If root cause is agent_error, return kind "policy_rule" with a single sentence rule.

Always include title (short, for the reviewer) and rationale (2-3 sentences: why this fixes the cluster and which evidence supports it).
```
