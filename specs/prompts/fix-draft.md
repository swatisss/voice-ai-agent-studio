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

`cluster_name`, `cluster_description`, `root_cause`, `evidence` (per call: caller goal, gap summary, human resolution note), `existing_tools` (name + description), `tool_catalog` (endpoints available in the business API that are not yet tools: method, path, description, parameters), `existing_doc_titles`, `attached_articles` (up to 3 attached articles closest to the gap: id, title, content), `unattached_tools` (tenant tools the agent lacks: name, description).

# Output

| Root cause | JSON |
|---|---|
| `missing_knowledge` | `{"kind":"knowledge_article","title":"...","rationale":"...","article":{"title":"...","content_markdown":"..."}}` |
| `missing_skill` | `{"kind":"skill","title":"...","rationale":"...","skill":{name, description, instructions, required_tools, escalate_when},"tool":<tool definition or null>,"existing_tool_name":<string or null>}` |
| `agent_error` | `{"kind":"policy_rule","title":"...","rationale":"...","rule":"..."}` |
| `missing_knowledge`, an attached article covers it | `{"kind":"knowledge_edit","title":"...","rationale":"...","doc_id":"...","article":{"title":"...","content_markdown":"..."}}` |
| `missing_skill`, an existing tool fits | `{"kind":"tool_attach","title":"...","rationale":"...","tool_name":"..."}` |

# Prompt

```text
You improve an AI phone assistant for a health insurer. A cluster of calls went wrong for the same reason: they were escalated to human specialists, the caller was unhappy, or the assistant could not find an answer or complete a lookup. Using what actually resolved these calls, draft one change to the assistant so it can handle them itself next time.

Cluster: {{cluster_name}} — {{cluster_description}}
Root cause: {{root_cause}}

Evidence (caller goal, gap, what resolved it — usually a human specialist's note):
{{evidence}}

Attached knowledge articles closest to this gap:
{{attached_articles}}

Other existing knowledge articles: {{existing_doc_titles}}
Tools the assistant has: {{existing_tools}}
Tools the business already has that the assistant does not:
{{unattached_tools}}
Business API endpoints not yet available as tools:
{{tool_catalog}}

Rules:
- Use only facts that appear consistently in the resolution notes. If notes disagree, use the most common answer and mention the uncertainty in the rationale.
- Never include member-specific data (names, IDs, dates of birth, claim numbers) in the change.
- Never add medical advice.
- Write for a voice assistant: short sections, plain language, concrete steps, deadlines and documents.
- Prefer the smallest change that fixes the cluster.

If root cause is missing_knowledge: if one of the attached articles covers this topic but lacks the answer, return kind "knowledge_edit" with its doc_id and the full revised article (keep everything that is still right, add or correct what the evidence shows); otherwise return kind "knowledge_article" with a new article in Markdown: a title, a one-paragraph overview, then "##" sections for eligibility or deadlines, how to do it, what documents are needed, and what happens next.
If root cause is missing_skill: if one of the tools the business already has fits and the assistant's instructions already cover the steps, return kind "tool_attach" with its tool_name; otherwise return kind "skill": a skill with numbered instructions that starts with identity verification when member data is involved, plus either existing_tool_name (if a tool fits) or a tool definition for one catalog endpoint (name in snake_case, description, method, url exactly as in the catalog, parameters as a JSON Schema object, requires_verification true for member data, is_verification false, timeout_s 8).
If root cause is agent_error, return kind "policy_rule" with a single sentence rule.

Always include title (short, for the reviewer) and rationale (2-3 sentences: why this fixes the cluster and which evidence supports it).
```
