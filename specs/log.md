# Directory Update Log

## 2026-10-07 (CP-0009 simplified UI, left navigation, Echo Mind branding)
* **Creation**: [CP-0009](changes/cp-0009-simplified-ui-sidebar-and-branding.md) (accepted and implemented the same day); new acceptance IDs UI-27, UI-28, UI-29, UI-30. Review answers: remove the Top clusters cost column (yes), no rename of the demo company in seed data (no), all top menu items move to the left sidebar (yes).
* **Update**: [Dashboard](ui/dashboard.md) - four-tile stat row (calls, containment rate, escalated to human, response time); cost saved and average LLM cost tiles removed from the display, Top clusters loses its cost column (UI-30), API unchanged. [App shell](ui/app-shell.md) - left sidebar with fixed "Echo Mind / Voice Agent Studio" brand, business-unit switcher and provider status at the bottom, mobile drawer; UI-19 and UI-20 reworded. [Design system](ui/design-system.md) - layout section for the sidebar. [UI index](ui/index.md) and [scope](product/scope.md) - one-liners.
* Implemented in the web app only (`shell.tsx`, `globals.css`, `layout.tsx`, `app/page.tsx`, one line in `test-call/page.tsx`); the API is untouched. UI-27…UI-30 are verified by hand in the browser (375, 1024, 1280 and 1440 px, light and dark) and listed in `scripts/acceptance-baseline.txt`; UI-19, UI-20 and UI-29 were re-checked against the sidebar. All touched specs are `status: stable`.

## 2026-10-07 (CP-0008 OpenAI as a third LLM provider)
* **Creation**: [CP-0008](changes/cp-0008-openai-provider.md) (accepted and implemented the same day), [ADR-0007](decisions/adr-0007-openai-provider.md); new acceptance IDs LG-08…LG-11. Implemented with 5 new tests (stubbed OpenAI client, no network) and an updated DEV-06 test; a live check with a real OpenAI key is still pending (no key was configured when it was built).
* **Update**: [LLM gateway](architecture/llm-gateway.md) - `openai` provider, `gpt-4.1-mini` / `gpt-4.1-nano`, OpenAI as the last fallback of every role, quirks; [dev launcher](build/dev-launcher.md) (DEV-06 widened); [deployment](architecture/deployment.md) and [GCP runbook](build/runbook-gcp.md) - optional secrets, `/healthz` shape; [local runbook](build/runbook-local.md) - OpenAI-only setup, role lines, duplicate-key trap, Groq 429 advice; [app shell](ui/app-shell.md); wording in [tech stack](architecture/tech-stack.md), [system overview](architecture/system-overview.md), [demo script](product/demo-script.md), [ADR-0003](decisions/adr-0003-llm-gateway.md).

## 2026-10-06 (CP-0006 Customer Support & Channels use cases)
* **Creation**: [CP-0006](changes/cp-0006-customer-support-use-cases.md), [use cases](product/use-cases.md) (UC-02), [call modes](architecture/call-modes.md) (OB-01…06), mode prompts ([inbound](prompts/mode-inbound.md), [outbound](prompts/mode-outbound.md), [internal](prompts/mode-internal.md)); new acceptance prefixes `UC`, `OB`.
* **Update**: [Members, policies and claims](demo-data/members-and-claims.md) and [Evergreen Health](demo-data/evergreen-health.md) rewritten for the seven use cases (UC-01, UC-03, UC-04); [mock insurance API](api/mock-healthcare-api.md) extended and pharmacy/ID-card endpoints removed (MOCK-05…12); [call history](demo-data/call-history.md) re-expressed in the new intents (UC-05); knowledge bases regrouped per agent (customer care, renewals, onboarding, internal, sandbox), pharmacy removed.
* **Update**: [REST API](api/rest-api.md) (use cases, outbound targets, `context`, `direction`), [agent config](data/agent-config.md) (`mode`, `outbound`), [data model](data/data-model.md) (`use_cases`, `calls.direction`, 19 tables), [agent runtime](architecture/agent-runtime.md), [system prompt](prompts/agent-system-prompt.md) (`mode_instructions`).
* **Update**: [Test call](ui/test-call.md) (use-case gallery, outbound placement; UI-24, UI-25), [agent builder](ui/agent-builder.md) (mode; UI-26), [calls](ui/calls.md) (direction); [vision](product/vision.md), [scope](product/scope.md), [glossary](product/glossary.md), [demo script](product/demo-script.md).
* **Update**: [Conventions](process/conventions.md) - frontmatter values containing a colon and a space must be quoted, and `scripts/spec_check.py` enforces it (SDD-02); seven knowledge articles with unquoted descriptions had been skipped by the OKF importer and are fixed.
* **Update**: [Design system](ui/design-system.md) and [App shell](ui/app-shell.md) - between 768 and 1279 px only the active navigation item shows its label so the header does not scroll sideways.
* **Update**: [Evergreen Health](demo-data/evergreen-health.md) - how the spoken opening splits into greeting and disclosure; UC-03 now states the isolation guarantee that tests can check; [call analysis prompt](prompts/call-analysis.md) - intent examples use the new use-case labels.

## 2026-10-06 (CP-0007 turn detection and personas)
* **Creation**: [CP-0007](changes/cp-0007-turn-detection-and-personas.md), [turn detection](architecture/turn-detection.md) (TD-01…08), [personas](architecture/personas.md) (PER-01…06), [ADR-0006](decisions/adr-0006-turn-detection.md), [turn end check prompt](prompts/turn-end-check.md), [personas page](ui/personas.md) (UI-21).
* **Update**: [Voice pipeline](architecture/voice-pipeline.md) — turn aggregation delegated to the turn-detection spec, VAD stop 0.2 s, barge-in setting, TTS live updates, live controls.
* **Update**: [LLM gateway](architecture/llm-gateway.md) — optional `turn` role; [agent runtime](architecture/agent-runtime.md) — `set_persona`; [agent config](data/agent-config.md) and [data model](data/data-model.md) — `persona_id`, `voice.turn_detection`, `personas` table (18 tables); [REST API](api/rest-api.md) — personas, call overrides, `PATCH /api/calls/{id}/live`.
* **Update**: [Agent builder](ui/agent-builder.md) — library persona and Voice tab (UI-22); [Test call](ui/test-call.md) — Live controls (UI-23); navigation gains Personas; new acceptance prefixes `TD`, `PER`.

## 2026-10-06 (CP-0005 insurer portal theme)
* **Creation**: [CP-0005](changes/cp-0005-insurer-portal-theme.md).
* **Update**: [Design system](ui/design-system.md) — rewritten for the health-insurer portal look: brand-blue tokens, top-header layout, pill controls, accessibility rules; UI-18 (contrast, automated).
* **Update**: [App shell](ui/app-shell.md) — top header with horizontal navigation replaces the sidebar; UI-19, UI-20.

## 2026-10-06 (CP-0004 dev launcher)
* **Creation**: [CP-0004](changes/cp-0004-one-command-dev-launcher.md) and the [dev launcher](build/dev-launcher.md) spec (DEV-01…06); new acceptance prefix `DEV` in [conventions](process/conventions.md).
* **Update**: [Local runbook](build/runbook-local.md) — first run uses `scripts/dev.py`; the manual web dev server needs `NEXT_PUBLIC_API_BASE`.

## 2026-10-06 (CP-0003 .env role overrides)
* **Creation**: [CP-0003](changes/cp-0003-env-file-role-overrides.md) — `LLM_ROLE_<ROLE>` honored from `apps/api/.env`.
* **Update**: [LLM gateway](architecture/llm-gateway.md) — override sources and LG-07.
* **Update**: [Local runbook](build/runbook-local.md) — "Running without some keys" (no Deepgram, OpenRouter only, no LLM key).

## 2026-10-06 (CP-0002 spec enforcement)
* **Creation**: [CP-0002](changes/cp-0002-spec-enforcement-and-onboarding.md) — CI gate, PR-level rules, acceptance ratchet, setup script, README.
* **Update**: [SDD workflow](process/sdd-workflow.md) — guardrails restated as hooks / CI / branch protection; log, lifecycle and coverage-ratchet rules; test-only changes exempt from spec-first; SDD-01 refined, SDD-05…09 added.
* **Update**: [Local runbook](build/runbook-local.md) — first run uses `scripts/setup.py`.

## 2026-10-06 (close-out)
* **Update**: [CP-0001](changes/cp-0001-initial-platform.md) set to `implemented`; open items are the live-key spikes S1–S3 in [spikes](verification/spikes.md).

## 2026-10-06 (web + infra, CP-0001 T18–T22)
* **Update**: [Deployment](architecture/deployment.md) — static handler maps Next.js 16 segment prefetch paths (`__next.a.b.__PAGE__.txt` → `__next.a/b/__PAGE__.txt`).
* **Update**: [Design system](ui/design-system.md) — component list matches the built components.
* **Update**: [Task plan](build/task-plan.md) — T18–T22 done: web app (Next.js 16 static export), `infra/Dockerfile`, `infra/deploy-cloudrun.sh`. UI acceptance (UI-*) verified manually in the browser with the fake LLM; live-key checks remain in [spikes](verification/spikes.md).

## 2026-10-06 (backend build, CP-0001 T01–T17)
* **Update**: [Agent runtime](architecture/agent-runtime.md) — the runtime speaks the handoff itself after `escalate_to_human` (no extra LLM round) and supplies a default goodbye after `end_call`.
* **Update**: [LLM gateway](architecture/llm-gateway.md) — realtime `max_tokens` 800 (reasoning tokens count), streaming-usage and `json_schema`→`json_object` fallback notes.
* **Update**: [Escalation](architecture/escalation.md) — evaluation calls never reach the human console.
* **Update**: [Call history](demo-data/call-history.md) — seed window is relative to the seed date.
* **Update**: [Spikes](verification/spikes.md) — verified package versions and Pipecat 1.12 API facts; [tech stack](architecture/tech-stack.md) and [local runbook](build/runbook-local.md) now say Node.js LTS 24.
* **Update**: [Task plan](build/task-plan.md) — T01–T17 done (66 backend tests passing).

## 2026-10-06
* **Initialization**: Created the spec bundle for the multi-tenant voice AI agent platform (healthcare & insurance demo domain) under [CP-0001](changes/cp-0001-initial-platform.md).
* **Creation**: Established the [SDD workflow](process/sdd-workflow.md), [conventions](process/conventions.md) and [change proposal template](process/change-proposal-template.md).
* **Creation**: Product, architecture, data, API, prompt, UI, decision, demo-data, build and verification specs.
