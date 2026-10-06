# AGENTS.md — instructions for coding agents

This repo practices **spec-driven development (SDD)**. The `specs/` folder is an OKF bundle and the **source of truth**. Read `specs/index.md` first, then the specs relevant to your task.

## Golden rules

1. **Spec first.** Never change behavior, contracts, data model, prompts or UI without first changing the governing spec. If a request is not covered by the specs, draft a change proposal (`specs/changes/cp-NNNN-*.md`, template in `specs/process/change-proposal-template.md`) and the spec edits, then stop for human review.
2. **Specs and code ship together** in one commit. Code-only commits must say `[no-spec]` and must not change behavior (refactor, deps, tooling, or fixing code to match an existing acceptance criterion).
3. **Cite acceptance IDs.** Tests carry `Covers: XX-NN` in their docstring. Modules start with `Spec: /path/to/spec.md`.
4. **Prompts live in `specs/prompts/`** and are loaded verbatim at runtime. Change the spec file, not a copy in code.
5. **Log every spec change** in `specs/log.md` (newest date first) and keep `specs/build/task-plan.md` statuses and CP `cp_state` current.
6. **Synthetic data only.** Never add real PHI/PII or secrets anywhere.
7. **CI is the gate, not the hooks.** `--no-verify` does not get you past `.github/workflows/ci.yml`. A stable acceptance ID needs a test that cites it (or an approved line in `scripts/acceptance-baseline.txt`); a spec you are still implementing stays `status: draft`.

Full workflow: `specs/process/sdd-workflow.md`. Writing rules: `specs/process/conventions.md`.

## Repo map

| Path | What |
|---|---|
| `specs/` | OKF spec bundle (process, changes, product, architecture, data, api, prompts, ui, decisions, demo-data, build, verification) |
| `apps/api/` | Python 3.12 FastAPI service, package `voiceai` (uv project) |
| `apps/api/voiceai/` | `routes/`, `runtime/`, `voice/`, `llm/`, `knowledge/`, `learning/`, `mock/`, `seed/`, `db.py`, `models.py`, `events.py`, `jobs.py` |
| `apps/api/config/models.yaml` | LLM roles → provider/model refs, prices |
| `apps/api/tests/` | pytest suite (fake LLM, hash embedder, temp SQLite) |
| `apps/web/` | Next.js static-export web app (Tailwind) |
| `infra/` | Dockerfile and Cloud Run deploy script |
| `scripts/spec_check.py` | OKF lint, index/link/acceptance checks, spec-first rule |
| `.githooks/` | pre-commit and commit-msg hooks running `spec_check.py` |

## Commands

```bash
python scripts/setup.py --install            # new machine: hooks, apps/api/.env, dependencies
python scripts/spec_check.py --ci --base origin/main   # exactly what CI enforces (spec-first, log, lifecycle, coverage ratchet)
python scripts/spec_check.py                 # quick spec lint (repo root)
cd apps/api && uv sync && uv run pytest      # backend tests
cd apps/api && uv run voiceai serve          # API + web (if built) on :8000
cd apps/api && uv run voiceai seed --reset   # reseed demo data
cd apps/web && npm install && npm run dev    # web dev server on :3000
cd apps/web && npm run build                 # static export to apps/web/out
```

## Implementing a change proposal

1. Read the CP and every spec it links. Confirm `cp_state: accepted`.
2. Work the CP's tasks in order. For each: write/adjust tests citing acceptance IDs, implement, run checks.
3. Update `specs/log.md`, set touched specs to `status: stable`, set the CP to `cp_state: implemented`, update `specs/build/task-plan.md` if the CP added tasks there.
4. One commit (or PR) with specs + code; message starts with the CP id, e.g. `CP-0002: Add prior auth status skill`.

## Code conventions

* Python: async everywhere on request paths; type hints; Pydantic models for API I/O; repository helpers always take `tenant_id`; no network in unit tests.
* Pipecat imports only inside `voiceai/voice/`.
* Web: client components only (static export); query-string routes for details; `lib/api.ts` for all HTTP; `// Spec: /ui/<page>.md` at the top of page files.
* Never hard-code model IDs in code — use roles via `voiceai.llm.gateway`.
