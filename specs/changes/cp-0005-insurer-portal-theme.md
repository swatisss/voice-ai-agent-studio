---
type: Change Proposal
title: CP-0005 Health-insurer portal look and feel
description: Restyle the web app as a trusted health-insurer portal - blue brand palette, top navigation, pill buttons, soft cards, large friendly type, WCAG AA contrast - without changing behavior.
status: stable
cp_state: implemented
tags: [ui, design, accessibility]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-06T00:00:00Z" }
---

# Why

The studio is shown to insurance stakeholders. It should feel like the customer portals they know: calm and trustworthy, a confident blue, generous spacing, large readable type, rounded pill controls, and strong accessibility - not a developer tool. The current teal sidebar layout reads as an engineering console.

# What changes

* New design tokens (light and dark): deep-navy text, brand blue primary, blue-grey backgrounds. Every text/surface pair meets WCAG AA (4.5:1) and this is checked by an automated test.
* App shell: a white top header (brand mark, product name, horizontal navigation with a thick active underline, business-unit switcher, provider status) replaces the left sidebar; the navigation collapses into a menu on small screens; a skip-to-content link is added.
* Components: pill-shaped buttons (solid primary, outlined secondary), 16 px card radius with a soft shadow, thicker focus rings, comfortable control height, larger headings.
* The brand shown in the header is the business unit's brand (the part of the tenant name before ` · `), so each tenant looks like its own portal. No logo artwork is bundled; the mark is a generic icon.
* No behavior, API or data change.

# Affected specs

* [/ui/design-system.md](/ui/design-system.md) — rewritten: brand look, tokens, layout, components, accessibility.
* [/ui/app-shell.md](/ui/app-shell.md) — top-navigation layout; UI-19 and UI-20.

# Acceptance criteria

UI-18 (automated), UI-19 and UI-20 (verified in the browser) in the specs above.

# Tasks

1. Spec edits (done first).
2. `apps/web/app/globals.css` tokens, `components/ui.tsx` styles, `components/shell.tsx` layout — covers UI-19, UI-20.
3. `apps/api/tests/test_design_tokens.py` — covers UI-18.
4. Add UI-19 and UI-20 to `scripts/acceptance-baseline.txt` (manual verification).

# Risks and rollout

* Visual only; every page uses semantic classes, so the token change carries most of it. Dark mode must be re-checked.
* Out of scope: per-tenant color customization (a candidate follow-up: a `theme` column on tenants), bundled brand logos or custom web fonts.
