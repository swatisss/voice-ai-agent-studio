# Directory Update Log

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
