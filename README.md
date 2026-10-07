# Voice Agent Studio

A multi-tenant voice AI agent platform. A business unit (a *tenant*) provides **knowledge, tools, skills and a persona** and gets an agent that:

1. **Resolves** routine calls end to end (human cost ≈ $7–12/call vs. under $1.20 for AI).
2. **Escalates** hard or risky calls to a human with a *groundwork packet* (summary, intent, what was tried, sentiment, next step) so nobody starts from zero.
3. **Learns**: every escalation is analyzed, recurring gaps are clustered, fixes are drafted from what human specialists actually said, proven by simulated replays, and published after a human approves.

The demo domain is **Evergreen Health**, a fictional health insurer whose business unit *Customer Support & Channels* serves seven use cases: Policy Inquiry & Status, Claims Status Tracking, Document Center & Green Card, Outbound Renewal Calls, Policyholder Onboarding, an Internal Knowledge Assistant and Coverage Information Support ([`specs/product/use-cases.md`](specs/product/use-cases.md)). All data is synthetic, never use real PHI. Voice is tested from the browser (no telephony yet); LLMs run on Groq with OpenRouter as a switchable fallback.

> **This repo is spec-driven.** `specs/` is the source of truth; code is generated from it and changes start there. Read [Spec-driven development](#spec-driven-development) before changing anything.

---

## Contents

- [Run it](#run-it)
- [Spec-driven development](#spec-driven-development)
- [Starting on a new machine](#starting-on-a-new-machine)
- [Generating code from specs](#generating-code-from-specs)
- [Keeping specs up to date (enforcement)](#keeping-specs-up-to-date-enforcement)
- [Repo map and commands](#repo-map-and-commands)
- [Troubleshooting](#troubleshooting)

---

## Run it

Prerequisites: Python 3.12, [uv](https://docs.astral.sh/uv/), Node.js LTS (24.x), Git. Keys: `GROQ_API_KEY` (agent), `DEEPGRAM_API_KEY` (voice), optional `OPENROUTER_API_KEY`.

```bash
python scripts/setup.py --install      # once: hooks, apps/api/.env, uv sync, npm ci   (Windows: py -3 scripts/setup.py --install)
# edit apps/api/.env and add your keys

python scripts/dev.py                  # the whole stack from one terminal (Windows: py -3 scripts/dev.py)
```

`dev.py` starts the web app (<http://localhost:3000>, hot reload) and the API (<http://localhost:8000>, auto-reload) together, checks tools, dependencies, keys and ports first, interleaves both services' logs with `[web]` / `[api]` prefixes, prints `READY - open …` when both answer (the first API start seeds the demo data, about a minute), and **Ctrl+C stops everything**.

| Command | What it does |
|---|---|
| `python scripts/dev.py` | Dev mode: web `:3000` + API `:8000`, both auto-reloading |
| `python scripts/dev.py --single-origin` | Builds the web export, then serves everything from the API on `:8000` (what Cloud Run runs; best for demos) |
| `python scripts/dev.py --fake` | No LLM keys: scripted fake LLM, hash embeddings, **separate** database (`apps/api/data/fake.db`); UI and plumbing only |
| `python scripts/dev.py --check` | Pre-flight checks only (missing tools or dependencies, busy ports, missing keys) |
| `--api-port N`, `--web-port N`, `--no-reload`, `--install` | Change ports, disable API reload, or run `setup.py --install` first |

Open the web URL, pick a tenant, and follow the three-act script in [`specs/product/demo-script.md`](specs/product/demo-script.md): *resolve* a claim question, *escalate* an appeal with a packet, *learn* the "add a newborn" gap and ship the fix. **Test call** shows a gallery of the seven use cases (select one to see what to say and which demo caller to use), places **outbound** renewal and onboarding calls (the agent speaks first), and its **Live controls** switch the persona and the turn detection (normal or semantic) in the middle of a call. Use a headset for voice; the **Type** tab is a full fallback.

**No Deepgram key yet?** Set only `GROQ_API_KEY` and use the **Type** tab on *Test call*: everything works except the microphone (the launcher prints a warning, not an error). OpenRouter-only and no-LLM-key setups are in [`specs/build/runbook-local.md`](specs/build/runbook-local.md#running-without-some-keys); the launcher reference is [`specs/build/dev-launcher.md`](specs/build/dev-launcher.md).

Deploying to GCP Cloud Run: [`specs/build/runbook-gcp.md`](specs/build/runbook-gcp.md).

---

## Spec-driven development

**Idea:** the *what and why* lives in Markdown specs that humans review; the *how* is code that an AI coding agent (or you) writes against them. When code and spec disagree, the spec wins until a spec change says otherwise.

`specs/` is an [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) bundle: plain Markdown with YAML frontmatter, an `index.md` per folder, a dated `log.md`. Start at [`specs/index.md`](specs/index.md).

| Folder | What it defines |
|---|---|
| `process/` | The workflow below, writing conventions, the change-proposal template |
| `changes/` | **Change proposals** (`cp-NNNN-*.md`) — the entry point for every behavior change |
| `product/` | Vision, scope, glossary, demo script, healthcare compliance rules |
| `architecture/` | One spec per component, each ending in **acceptance criteria with IDs** (e.g. `ES-01`) |
| `data/`, `api/`, `ui/` | Tables and config schemas, REST/WebSocket/SSE contracts, one spec per page |
| `prompts/` | **Every LLM prompt**, loaded verbatim by the code — changing agent behavior is a spec change |
| `decisions/` | Why each technology was chosen (ADRs) |
| `demo-data/` | Seed tenants, mock records, call history, knowledge articles |
| `build/` | Ordered task plan (T01–T22), definition of done, runbooks |

### The loop for every change

```
idea ─▶ 1. change proposal ─▶ 2. spec edits ─▶ 3. human review ─▶ 4. implement ─▶ 5. verify ─▶ 6. close
        specs/changes/cp-N      draft + new IDs    set accepted     code + tests      spec_check +     specs stable,
                                                                    cite IDs          tests + build    log, one commit
```

| You want to… | Do this |
|---|---|
| Add or change behavior (feature, API field, UI, **prompt**) | Full loop. Run `/spec-change <idea>` in Claude Code — it drafts the CP and spec edits and **stops for your review**. |
| Implement an accepted proposal | `/spec-implement CP-0003` — implements tasks in order, writes tests that cite acceptance IDs, runs checks, flips specs to `stable`, prepares one commit. |
| Fix a bug where code violates an existing criterion | Fix the code, add or repair the test citing the ID, commit with `[no-spec]`. |
| Fix a bug where the spec was wrong or silent | A small CP: fix the spec first, then the code. |
| Typo, link, clarification in specs | Edit the spec and add a `specs/log.md` line. |
| Refactor, dependency bump (no behavior change) | Commit with `[no-spec]`. |

Rules of the road (details in [`specs/process/sdd-workflow.md`](specs/process/sdd-workflow.md) and [`specs/process/conventions.md`](specs/process/conventions.md)):

- **Spec first**, and **specs + code ship together** in one commit/PR.
- Acceptance criteria are `- **XX-NN** — Given …, when …, then …`; IDs are never reused.
- Tests cite them (`Covers: XX-NN` in the docstring); modules start with `Spec: /path.md`.
- A spec being edited is `status: draft`; it becomes `stable` when implemented. A CP goes `proposed → accepted → implemented`.

### Example: adding a feature

```text
/spec-change Let callers request a premium invoice for a previous year
   → creates specs/changes/cp-0008-past-premium-invoices.md, edits specs/architecture/tools-and-skills.md
     and specs/api/mock-healthcare-api.md, adds acceptance IDs (e.g. MOCK-13), logs it. No code yet.
You: review `git diff specs/`, tweak, set cp_state: accepted
/spec-implement CP-0008
   → mock API + tool + skill + tests ("Covers: MOCK-13"), checks green, specs stable, one commit.
```

---

## Starting on a new machine

Works the same on Windows, macOS and Linux.

1. **Install prerequisites** (Git, Python 3.12, uv, Node.js LTS)

   ```powershell
   # Windows (PowerShell); open a new terminal afterwards
   winget install --source winget Git.Git
   winget install --source winget Python.Python.3.12
   winget install --source winget OpenJS.NodeJS.LTS
   py -3.12 -m pip install --user uv        # then run it as: py -m uv ...   (winget install astral-sh.uv also works)
   ```

   ```bash
   # macOS
   brew install git python@3.12 node uv
   # Linux: install git, python3.12, Node.js LTS with your package manager (or nvm), then: pipx install uv
   ```

   Docker is only needed to build the Cloud Run image. A coding agent is only needed to *generate* code (see below).

2. **Clone and bootstrap**

   ```bash
   git clone <your-private-repo-url> voice-ai && cd voice-ai
   python scripts/setup.py --install     # Windows: py -3 scripts/setup.py --install
   ```

   This enables the git hooks (`core.hooksPath = .githooks`), creates `apps/api/.env` from the example (never overwrites yours), installs locked dependencies (`uv.lock`, `package-lock.json` — identical on every machine), and runs the spec check.

3. **Add secrets** to `apps/api/.env` (git-ignored, never commit keys). Each machine needs its own copy.

4. **Verify the machine is ready**

   ```bash
   python scripts/spec_check.py --ci            # specs consistent
   cd apps/api && uv run pytest                 # 74 tests, no network or keys needed
   cd ../web && npm run build                   # static export
   ```

Line endings are normalized by `.gitattributes` (LF), so Windows/macOS/Linux diffs stay clean. The hooks only need a Python 3.9+ on `PATH` (they fall back to `py -3` on Windows).

---

## Generating code from specs

The agent contract is [`AGENTS.md`](AGENTS.md) (an open convention that many coding agents read; Claude Code reads `CLAUDE.md`, which imports it). It tells the agent that specs are the source of truth, where things live, which commands to run, and the spec-first rules. Any machine, any agent: open the repo, point the agent at `AGENTS.md`.

### A. Incremental change (the everyday path)

Use the loop above. With **Claude Code**: `/spec-change …` then `/spec-implement CP-NNNN`. With **another agent** paste these:

```text
Read AGENTS.md and specs/process/sdd-workflow.md. I want: <idea>.
Draft a change proposal from specs/process/change-proposal-template.md and edit the affected
specs, new acceptance IDs included, status: draft. Log it in specs/log.md and run
python scripts/spec_check.py. Do NOT write application code. Stop for my review.
```

```text
Implement specs/changes/cp-NNNN-*.md (cp_state must be accepted). Follow AGENTS.md. Work its tasks
in order; tests cite acceptance IDs ("Covers: XX-NN"); then run python scripts/spec_check.py --ci,
cd apps/api && uv run pytest, and cd apps/web && npm run build. Mark specs stable, the CP
implemented, update specs/log.md, and prepare ONE commit containing specs and code.
```

### B. Rebuild everything from specs (new machine, new stack, or "does the spec really suffice?")

Start from an empty `apps/` directory and give the agent the bundle:

```text
You are building this product from scratch. The only inputs are AGENTS.md and the specs/ bundle.
Read specs/index.md, then specs/build/task-plan.md. Execute tasks T01 to T22 in order. For each task read
the specs it lists, implement them exactly (contracts, schemas, prompts verbatim from specs/prompts/),
write tests that cite the task's acceptance IDs, and keep specs/build/task-plan.md statuses current.
When something is ambiguous or missing from the specs, propose a spec edit instead of guessing.
Verify with: python scripts/spec_check.py --ci, uv run pytest, npm run build.
```

Expect equivalent behavior, not identical code. What proves it: the acceptance criteria, each backed by tests (`Covers: …`), the spec checker, and the demo script. Every time the agent has to guess, that's a hole in the spec: fix the spec, not just the code. Good practice before a hackathon: run (B) once in a scratch repo and patch the specs where the agent went wrong.

---

## Keeping specs up to date (enforcement)

Process alone drifts, so the rules are checked mechanically, in three layers. Only the last one can't be skipped from a developer's laptop.

| Layer | Where | What it does |
|---|---|---|
| **1. Git hooks** (local) | `.githooks/`, enabled by `scripts/setup.py` | `pre-commit` lints the bundle; `commit-msg` rejects behavior-code commits that don't touch `specs/` (unless `[no-spec]`). Fast feedback, but bypassable with `--no-verify`. |
| **2. CI** | [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | Runs on every PR and push to `main`: `spec_check.py --ci --base origin/main`, backend tests, web build. |
| **3. Branch protection** | GitHub settings (below) | Makes those jobs required and a review mandatory, so nothing merges around the rules. |

What `scripts/spec_check.py` enforces (full list: [`sdd-workflow.md`](specs/process/sdd-workflow.md#guardrails-automated)):

| Rule | Fails when |
|---|---|
| OKF lint, index coverage, links | A spec lacks frontmatter/`type`, isn't listed in its `index.md`, or has a broken link |
| **Spec-first** (per commit and whole PR) | Behavior code under `apps/` changed without any spec change. Tests and lock files are exempt; refactors say `[no-spec]` (or the `no-spec` PR label) |
| **Log** | A spec changed but `specs/log.md` has no entry |
| **Lifecycle** | Code ships in a PR that touches a `draft` spec or a `proposed` change proposal |
| **Coverage ratchet** | A `stable` spec has an acceptance ID that no test cites. The 19 criteria verified by hand are listed in [`scripts/acceptance-baseline.txt`](scripts/acceptance-baseline.txt); that list may only shrink |
| **No dangling citations** | A test cites an acceptance ID that no spec defines |

### One-time GitHub setup (needs repo admin; can't be done from code)

1. Create the **private** repository and push `main`.
2. *Settings → Branches → Add rule* for `main`: **Require a pull request before merging** (1 approval), **Require status checks to pass** → select `Specs are in sync`, `Backend tests`, `Web build`, **Require branches to be up to date**, and **Do not allow bypassing the above settings**.
3. Add `.github/CODEOWNERS` so spec changes need a spec owner (use your GitHub handle):

   ```text
   /specs/                          @your-handle
   /scripts/acceptance-baseline.txt @your-handle
   /.github/                        @your-handle
   ```

   and enable *Require review from Code Owners* in the branch rule.
4. Create a `no-spec` label (maintainers only) for the rare pure-refactor PR that has no spec change.

### What can't be checked mechanically

A script can verify that specs, log, IDs and tests move together, but not that prose still *means* what the code does. Cover that gap with:

- **Acceptance-ID tests**: if a criterion has a test, behavior drift fails CI.
- **Review of the spec diff first**: the PR template asks for it; CODEOWNERS routes it.
- **A periodic audit** (monthly, or before demos), for example with your agent:

  ```text
  Audit specs against code. For each spec in specs/architecture, specs/api and specs/data, find where
  the implementation differs (behavior, field names, defaults, error codes). Report as a table. Propose
  spec fixes (as a change proposal) when the code is right, and list code bugs when the spec is right.
  ```

- Optionally mark reviewed specs with OKF's `verified:` / `stale_after:` frontmatter so old, unreviewed pages stand out.

---

## Repo map and commands

```text
specs/                 OKF spec bundle (source of truth)        scripts/    spec_check.py, setup.py, acceptance-baseline.txt
apps/api/              FastAPI + Pipecat backend (package voiceai)   infra/      Dockerfile, deploy-cloudrun.sh
apps/web/              Next.js 16 static-export UI                   .github/    CI workflow, PR template
.claude/commands/      /spec-change, /spec-implement                 AGENTS.md   instructions for coding agents
```

| Task | Command |
|---|---|
| Spec lint (strict, as CI) | `python scripts/spec_check.py --ci --base origin/main` |
| Backend tests | `cd apps/api && uv run pytest` |
| Web build / dev server | `cd apps/web && npm run build` · `npm run dev` (port 3000) |
| Run web + API together | `python scripts/dev.py` (`--single-origin` for the production-like shape) |
| Run only the API (serves a built web) | `uv run --project apps/api voiceai serve` (port 8000) |
| Reset demo data | `uv run --project apps/api voiceai seed --reset` |
| Chat with an agent in the terminal | `uv run --project apps/api voiceai chat --agent <id>` |
| Switch an LLM role | `LLM_ROLE_REALTIME=openrouter:openai/gpt-oss-120b` or edit `apps/api/config/models.yaml` |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `python` opens the Microsoft Store (Windows) | Use `py -3 …`, or disable the app-execution alias in *Settings → Apps → Advanced app settings* |
| `uv` not found after `winget install` | Open a new terminal, or `py -m uv …` |
| Commit rejected: "spec-first rule" | Update the governing spec and `specs/log.md` in the same commit, or add `[no-spec]` if behavior is unchanged |
| CI: "stable acceptance IDs with no test" | Add a test with `Covers: ID`, or keep the spec `status: draft` until implemented |
| `dev.py`: "port 8000 is already in use" | Another server is running. Stop it, or `--api-port 8001` (and `--web-port` for the web app) |
| `dev.py`: "dependencies are not installed" | `python scripts/dev.py --install` (or `python scripts/setup.py --install`) |
| Mic blocked in the browser | Use `http://localhost` or HTTPS; a headset avoids echo |
| Voice closes immediately (code 4500) | `DEEPGRAM_API_KEY` is missing; use the **Type** tab |
| Groq 429 | Free-tier limit: enable billing or set `LLM_ROLE_REALTIME` to an OpenRouter model |
| Everything slow the first time | fastembed downloads its ~70 MB model once |

Status and known gaps: live-key voice/LLM runs and the Cloud Run build haven't been verified yet — see [`specs/verification/spikes.md`](specs/verification/spikes.md).
