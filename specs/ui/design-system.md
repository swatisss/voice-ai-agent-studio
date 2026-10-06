---
type: UI Spec
title: Design system
description: Visual language, color tokens, typography, core components and copy rules for the web app.
status: stable
tags: [ui, design]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Principles

Calm, clinical, trustworthy — a healthcare operations tool. Dense but readable. Status is always shown with text + color, never color alone.

# Tokens (CSS variables, light and dark)

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#f7f8fa` | `#0f1216` | page |
| `--panel` | `#ffffff` | `#171b21` | cards |
| `--border` | `#e3e6ea` | `#2a3038` | hairlines |
| `--text` | `#14181f` | `#e8ebef` | body |
| `--muted` | `#5f6b7a` | `#9aa5b1` | secondary |
| `--accent` | `#0f766e` (teal 700) | `#2dd4bf` | primary actions, links |
| `--ok` | `#15803d` | `#4ade80` | resolved, passed |
| `--warn` | `#b45309` | `#fbbf24` | escalated, pending |
| `--bad` | `#b91c1c` | `#f87171` | failed, safety |
| `--info` | `#4338ca` | `#a5b4fc` | tool activity |

Dark mode follows `prefers-color-scheme`. Font: system UI stack; monospace for IDs and JSON. Radius 8px for controls, 12px for cards.

# Components (in `apps/web/components/ui/`)

`Button` (primary/secondary/ghost/danger, loading state), `Card`, `Badge` (tone: ok/warn/bad/info/neutral), `Tabs`, `Input`, `Textarea`, `Select`, `Field` (label + hint + error), `Table`, `Stat` (label, value, delta), `EmptyState`, `Spinner`, `Toast` (top-right, 4 s), `JsonView` (collapsible, monospace), `Modal` (in-flow overlay).

# Copy rules

* Sentence case for all labels and buttons ("Draft fix", not "Draft Fix").
* Outcomes: **Resolved** (ok), **Escalated** (warn), **Abandoned** (neutral). Root causes shown with human labels: "Missing knowledge", "Missing skill", "Policy required", "Safety", "Caller requested", "Tool error", "Speech error", "Agent error", "Other".
* Money: `$1,234`; rates: `68%`; durations: `1.2 s`.
* Every page has an empty state that tells the user the next action.
