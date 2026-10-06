---
type: Template
title: Change proposal template
description: Copy to specs/changes/cp-NNNN-short-slug.md to propose any behavior change before touching code.
status: stable
tags: [process, sdd, template]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

Copy everything below the line into `specs/changes/cp-NNNN-short-slug.md`, use the next free number, and add the file to [/changes/index.md](/changes/index.md).

---

```markdown
---
type: Change Proposal
title: CP-NNNN <short imperative title>
description: <one sentence: what changes and why>
status: draft
cp_state: proposed
tags: [<area>]
generated: { by: "<actor>", at: "<ISO datetime>" }
---

# Why
<problem, evidence (calls, metrics, user feedback), who benefits>

# What changes
<observable behavior after the change, in plain language>

# Affected specs
* [/architecture/...](/architecture/...) - <what changes in it>

# Acceptance criteria
- **XX-NN** — Given ..., when ..., then ...

# Tasks
1. <spec edits (done in this CP)>
2. <backend change> — covers XX-NN
3. <web change> — covers UI-NN
4. <tests / seed / docs>

# Risks and rollout
<data migration, demo impact, fallback>

# Out of scope
<explicitly not doing>
```
