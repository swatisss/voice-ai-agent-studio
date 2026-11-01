---
type: Change Proposal
title: CP-0028 Routing mode - embedding or a configured decision model
description: Routing runs on the embedding by default; a tenant can switch to a generic, Jev-compatible decision model configured by URL, key and model name, which falls back to the embedding when it is not configured, fails or is unsure; the routing suite compares both; vendor-named decision targets, the LLM decision target and local Laya are removed.
status: stable
cp_state: implemented
tags: [routing, evaluation, settings, configuration]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-01T00:00:00Z" }
---

# Why

Local Laya was measured on 2026-11-01 ([spikes](/verification/spikes.md) S5). It ran at about 2 s per decision against a 350 ms voice budget, and it was never confident on 22 answerable requests. The embedding picked the right agent first on all 22. The product owner decided:

* "I want to drop Laya … Remove these changes … for local Laya."
* "Don't take the name like Laya or Jev … keep it as decision model naming … so that I can switch to decision model by configuration and point it to [Jev] if I have the key. Otherwise embedding would run."

CP-0025 built three vendor-named targets (`jev`, `laya`, `llm`) with a failover chain. This CP replaces them with one configurable decision model and makes the embedding the default and the fallback. Decision 5 of [ADR-0012](/decisions/adr-0012-public-api-and-supervisor-routing.md) is superseded by it.

# What changes

* **Routing mode** (Settings → Front desk, `routing_mode`):
  * **`embedding`** (default): Stage A only. A clear win routes; anything else is unsure (clarifying question, then the default agent). No decision model is called.
  * **`decision_model`**: the decision model decides, given the Stage A shortlist (up to 5 candidates). An answer at or above the confidence threshold routes. If the model is not configured, blocked by PHI mode, fails (timeout, connection error, 429, 5xx, invalid answer) or is unsure, the **embedding** decides as in `embedding` mode. The fallback reason is recorded.
* **Stage A thresholds** become front-desk settings: `clear_win` (0.5–0.99, default 0.80) and `clear_margin` (0–0.5, default 0.10). The measurement shows today's bar sends most correct embedding picks to "unsure".
* **One decision model, configured by environment, no vendor names:**

  | Variable | Meaning |
  |---|---|
  | `DECISION_MODEL_URL` | Base URL of a Jev-compatible server (`POST {url}/v1/systemone`), e.g. `https://api.typesafe.ai`. Unset = not configured |
  | `DECISION_MODEL_API_KEY` | Bearer key, optional |
  | `DECISION_MODEL_NAME` | The `model` field sent, e.g. `jev-latest` |
  | `DECISION_MODEL_THRESHOLD` | Confidence needed, default 0.55; a tenant's `min_confidence` overrides it |
  | `DECISION_MODEL_HOSTED` | `1` (default) when a third party runs it: `PHI_MODE` then blocks it |

  `ROUTER_DECISION_TARGET`, `ROUTER_VOICE_TARGET`, `JEV_API_KEY`, `LAYA_BASE_URL`, `LAYA_API_KEY` and the `decision:` section of `models.yaml` are removed.
* **The LLM router is no longer a decision target.** The `router` role only writes clarifying questions. The router decision prompt is deprecated.
* **Compare in the product:** a routing-suite comparison run scores both modes on the same enabled cases:
  * right first choice
  * decided without asking
  * right when decided
  * vague requests asked about
  * latency p50 / p95

  The decision-model row shows "Not configured" without a URL. Evaluation → Routing shows the two side by side, with **Use this mode**.
* **Local Laya removed:** no Dockerfile, no dev-launcher service, no `.env` lines. The launcher is unchanged.
* `scripts/setup.py` fills an empty `PUBLIC_API_SECRET` like `TENANT_SECRETS_KEY`.

# Affected specs

* [/architecture/supervisor-routing.md](/architecture/supervisor-routing.md): Routing mode and Decision model sections replace Strategies and Decision targets (RTE-02, RTE-03, RTE-04, RTE-11 changed; RTE-12…RTE-15).
* [/architecture/llm-gateway.md](/architecture/llm-gateway.md): `router` role writes clarifying questions only; no `decision:` section (LG-14 changed).
* [/architecture/capability-catalog.md](/architecture/capability-catalog.md): comparison runs (CAT-09).
* [/architecture/deployment.md](/architecture/deployment.md): the decision-model variables; no Laya service.
* [/product/healthcare-compliance.md](/product/healthcare-compliance.md) (rule 11), [/product/glossary.md](/product/glossary.md), [/prompts/router-decision.md](/prompts/router-decision.md) (deprecated).
* [/api/rest-api.md](/api/rest-api.md): front-desk fields; `POST /api/routing/runs {compare}`.
* [/ui/evaluation.md](/ui/evaluation.md) (UI-63), [/ui/settings.md](/ui/settings.md) (UI-64).
* [/process/sdd-workflow.md](/process/sdd-workflow.md) (SDD-10), [/verification/spikes.md](/verification/spikes.md) (the measurement and the decision).

# Acceptance criteria

New: RTE-12, RTE-13, RTE-14, RTE-15, CAT-09, UI-63, UI-64, SDD-10. Changed: RTE-02, RTE-03, RTE-04, RTE-11, LG-14. Each is written in its spec.

# Tasks

1. Spec edits (this CP).
2. `voiceai/routing/decision.py`: one decision-model client from the `DECISION_MODEL_*` settings; no target chain; PHI mode for a hosted model — RTE-02, RTE-03, RTE-04.
3. `supervisor.route` by `routing_mode` and the thresholds, with embedding fallback and its reason — RTE-12…RTE-15.
4. Gateway: drop the `decision:` section; `router` role kept for clarifying questions — LG-14.
5. Comparison runs; front-desk fields; Evaluation comparison table and **Use this mode**; Settings mode and threshold controls — CAT-09, UI-63, UI-64.
6. `/healthz.router`: `{mode_default, decision_model: {configured, hosted, blocked_by_phi_mode}}` — RTE-11.
7. `scripts/setup.py` (SDD-10), `.env.example`, `infra/deploy-cloudrun.sh`.
8. Tests updated and added; the decision model is faked (no network).

# Risks and rollout

* Today's default (embedding first, then a decision target) becomes `embedding`, so the Stage B call goes away for every tenant until one chooses `decision_model`. Requests that were not a clear win now get a clarifying question, or the default agent, instead of a decision call. With the measured accuracy and the threshold settings this is expected to be better. The comparison shows it per tenant.
* The routing record keeps `stage_b` and `fallbacks`; old records with `jev`/`laya`/`llm` targets stay readable.

# Out of scope

Running a decision model ourselves; several decision models at once; per-agent modes.
