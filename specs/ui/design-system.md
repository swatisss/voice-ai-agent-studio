---
type: UI Spec
title: Design system
description: Health-insurer portal look and feel - brand palette tokens (light and dark), left-sidebar layout, pill controls, soft cards, accessibility rules and copy conventions for the web app.
status: stable
tags: [ui, design, accessibility]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-06T00:00:00Z" }
---

# Principles

The studio should feel like a trusted health-insurer customer portal: calm, clear and human, not a developer console.

* **Confident blue, lots of white.** One brand blue for actions and active states; deep navy for text; soft blue-grey page background; white cards.
* **Large, friendly type.** 16 px base, 1.5 line height, headings 600 weight in navy; no dense walls of text.
* **Round and soft.** Pill buttons, 16 px cards with a faint shadow, 10 px inputs.
* **Accessible first.** WCAG AA contrast everywhere, visible focus, keyboard-operable navigation, status never conveyed by color alone (always a text label), motion respects `prefers-reduced-motion`.
* The product's own name, **Echo Mind** with the caption "Voice Agent Studio", is the brand at the top of the sidebar; it does not change with the selected business unit. No third-party logos or fonts are bundled.
* **Simple over dense.** Show only the few metrics and navigation items the owner uses; everything else is one click deeper.

# Tokens (CSS variables in `apps/web/app/globals.css`; dark mode follows `prefers-color-scheme`)

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#F2F6FA` | `#0B1624` | page background |
| `--panel` | `#FFFFFF` | `#12223A` | cards, sidebar, mobile top bar, inputs |
| `--border` | `#D5DFEA` | `#26405F` | hairlines |
| `--text` | `#0E1F33` | `#E8EEF6` | body and headings |
| `--muted` | `#4A5D75` | `#9DB0C7` | secondary text |
| `--accent` | `#0A62B5` | `#5FB0FF` | primary actions, links, active nav |
| `--on-accent` | `#FFFFFF` | `#04223F` | text on `--accent` fills |
| `--accent-soft` | `#E3EFFB` | `#12365C` | selected / highlighted surfaces |
| `--ok` / `--ok-soft` | `#0E7A3D` / `#E4F5EA` | `#5CD68C` / `#10301E` | resolved, passed |
| `--warn` / `--warn-soft` | `#8A5200` / `#FFF1D9` | `#F5B94D` / `#3A2A0E` | escalated, pending |
| `--bad` / `--bad-soft` | `#B3261E` / `#FDE8E7` | `#FF8A82` / `#3B1715` | failed, safety |
| `--info` / `--info-soft` | `#3B4BB0` / `#E9ECFC` | `#A9B6FF` / `#1E2550` | tool activity |
| `--neutral-soft` | `#E8EDF3` | `#1B2E48` | neutral badges, bubbles |
| `--chart-warn` | `#C27400` | `#F5B94D` | warning series in charts (graphics only, not text) |

Typography: system UI stack (`Segoe UI`, `system-ui`, `-apple-system`, `Roboto`); monospace for IDs and JSON. Radius: controls pill (9999 px) for buttons and chips, 10 px for inputs, 16 px for cards.

# Layout

* **Sidebar** (768 px and wider; fixed, 16 rem wide, full height, `--panel` background, 1 px right border): the brand (mark, "Echo Mind", caption "Voice Agent Studio") on top; the navigation below it; the **business unit** switcher and provider status dots pinned at the bottom. Details in [/ui/app-shell.md](/ui/app-shell.md).
* **Navigation** items in order: Dashboard, Agents, Personas, Test call, Calls, Agent console (waiting badge), Insights (ready badge), stacked vertically, icon + label, 44 px row height. The active item has an `--accent-soft` background, accent text and a 4 px accent bar on its left edge; hover uses the same soft background.
* **Below 768 px**: no sidebar; a slim sticky top bar (brand + menu button) opens the sidebar as a drawer over the page.
* **Content**: fills the space right of the sidebar, max width 1280 px, 24 px page padding (16 px on phones), page titles at 28 px.
* A visually hidden **Skip to content** link is the first focusable element.

# Components (in `apps/web/components/ui.tsx`)

`Button` (primary solid, secondary outlined in accent, ghost, danger; pill; 40 px min height; loading state), `Card`, `Badge` (tone: ok/warn/bad/info/neutral/accent), `Tabs` (thick underline), `Input`, `Textarea`, `Select`, `Field` (label + hint + error), `Stat`, `EmptyState`, `Spinner`, `Toast` (top-right, 4 s), `JsonView`, `Modal`. Domain components: `Transcript`/`ActivityList`, `PacketCard`, `ClusterLabel`.

Focus: every interactive element shows a 3 px accent outline with 2 px offset on keyboard focus (`:focus-visible`).

# Copy rules

* Sentence case for labels and buttons ("Draft fix", not "Draft Fix").
* Outcomes: **Resolved** (ok), **Escalated** (warn), **Abandoned** (neutral). Root causes use human labels: "Missing knowledge", "Missing skill", "Policy required", "Safety", "Caller requested", "Tool error", "Speech error", "Agent error", "Other".
* Money `$1,234`; rates `68%`; durations `1.2 s`.
* Every page has an empty state that tells the user the next action.

# Acceptance

- **UI-18** — Given the light and dark token tables in `globals.css`, then the contrast ratio of every text/surface pair is at least 4.5:1: `text` and `muted` on `bg`, `panel` and `neutral-soft`; `accent` on `panel`, `bg` and `accent-soft`; `on-accent` on `accent`; and each of `ok`, `warn`, `bad`, `info` on its `-soft` surface.
