---
type: UI Spec
title: Customer chat app
description: The look and behavior of the separate customer chat - a branded header, a standing virtual-assistant disclaimer, bubbles, typing indicator, and clear notices when a specialist is being connected and has joined.
status: draft
tags: [ui, chat, escalation]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-16T00:00:00Z" }
---

# Page (`apps/chat`, `/`)

A single full-height chat in the style of an insurer's member site, centred on desktop and full-screen on a phone. It is not the Studio: no sidebar, no sign-in, none of the Studio's navigation or technical details. Spec: [/architecture/external-chat-app.md](/architecture/external-chat-app.md).

* **Header.** The brand name, a round avatar, the title "Member support" and a status line: **Virtual assistant** while the AI answers, **Connecting you to a specialist…** while an escalation waits, **Talking with {first name}, specialist** once accepted, **Chat ended** after the end.
* **Disclaimer.** A slim banner under the header that stays on screen: "You're chatting with a virtual assistant. It can make mistakes, so please don't share card numbers or passwords. In an emergency call 999." After a specialist joins it reads "You're now chatting with a person from our team."
* **Thread.** Caller bubbles right, in the brand colour; AI bubbles left, grey, labelled "Virtual assistant"; specialist bubbles left, white with a brand border, labelled "{first name} · Specialist". Each shows its time. The front desk's first line (greeting and disclosure) arrives automatically when the page opens. A typing indicator (three dots) shows while a reply is awaited. The thread scrolls to the newest line and announces new lines to screen readers (`aria-live="polite"`).
* **System notices** (centred, small, not a bubble): when the escalation is created "We're connecting you to a specialist. This usually takes a few minutes."; when accepted "You're now talking to a human agent." followed by the first name; at resolve "This chat has ended. Thanks for contacting us." with **Start a new chat**.
* **Composer.** A text box (max 2000 characters, Enter sends, Shift+Enter is a new line) and a **Send** button; disabled while sending and after the chat ends. While waiting for a specialist it stays enabled with the placeholder "Add anything the specialist should know".
* **Menu.** An **End chat** action in the header.
* Design tokens are the app's own, in the insurer blue of [/ui/design-system.md](/ui/design-system.md); contrast meets WCAG AA.

# Acceptance

- **UI-83** — Given a fresh load with the platform running, then the header shows the brand and **Virtual assistant**, the disclaimer is visible, and the thread starts with the front desk's greeting containing the disclosure; at phone width (375 px) nothing scrolls horizontally.
- **UI-84** — Given the customer asks for a person, then the AI's hand-off line appears, the notice "We're connecting you to a specialist" is shown and the header reads **Connecting you to a specialist…**; after the specialist accepts, the notice "You're now talking to a human agent." appears with their first name, the disclaimer text changes, and the specialist's typed reply appears in a bubble labelled "{first name} · Specialist".
- **UI-85** — Given the specialist resolves, then the notice "This chat has ended." appears, the composer is disabled and **Start a new chat** begins a fresh conversation; a reload during the chat restores the thread.
