---
type: Convention
title: Spec writing conventions
description: Frontmatter fields, normative language, acceptance criteria format, linking and code traceability rules for this bundle.
status: stable
tags: [process, sdd, okf]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Files and frontmatter

* One concept per file, kebab-case filename, ideally under 200 lines.
* Every concept starts with YAML frontmatter. Fields used in this repo:

| Field | Required | Notes |
|---|---|---|
| `type` | yes (OKF) | e.g. `Component Spec`, `API Contract`, `Prompt`, `UI Spec`, `Decision Record`, `Change Proposal`, `Knowledge Article` |
| `title` | yes (repo rule) | Human-readable name |
| `description` | yes (repo rule) | One sentence; reused in `index.md` entries |
| `status` | yes (repo rule) | `draft` while being changed, `stable` when implementable, `deprecated` |
| `tags` | recommended | YAML list |
| `generated` | recommended | `{ by: <actor>, at: <ISO datetime> }` — actor per OKF convention, e.g. `claude-code/claude-opus-5-5` |
| `verified` | after review | list of `{ by: "human:swati.verma", at: <ISO datetime> }`; makes the file *human-reviewed* |
| `cp_state` | change proposals only | `proposed` · `accepted` · `implemented` · `rejected` |

* Reserved files: `index.md` (listing, no frontmatter except root `okf_version`) and `log.md` (dated history, newest first).

# Normative language

* **MUST / MUST NOT** — required; violating it is a bug.
* **SHOULD** — expected unless there is a written reason.
* **MAY** — optional.

# Acceptance criteria

* Live under a `# Acceptance` heading at the end of the concept.
* Format: `- **PREFIX-NN** — Given <context>, when <action>, then <observable result>.`
* Prefixes: `SDD` process · `RT` runtime · `VO` voice · `LG` LLM gateway · `KN` knowledge · `TS` tools & skills · `ES` escalation · `FL` fleet learning · `EV` evaluation · `JB` jobs & events · `MT` multi-tenancy · `DEV` developer tooling · `DM` data model · `API` REST API · `MOCK` mock API · `UI` UI pages · `DEP` deployment.
* IDs are never reused. To retire one, strike it through (`~~ES-04~~`) and say why.

# Links

* Prefer bundle-absolute links (`/architecture/escalation.md`) — they survive file moves within folders.
* Link the first mention of another concept in each section.

# Code traceability

* Each backend module starts with a docstring line `Spec: /architecture/<file>.md` naming its governing spec(s).
* Each test docstring or name cites the acceptance IDs it covers, e.g. `"""Covers: ES-01, ES-02"""`.
* Web components cite their UI spec in a top-of-file comment: `// Spec: /ui/agent-console.md`.

# Writing style

* Describe behavior and contracts, not implementation detail, unless the detail is a contract (schemas, API shapes, prompts, enums).
* Use tables for enumerations and field lists; use numbered steps for flows.
* Keep examples realistic and consistent with [demo data](/demo-data/).
