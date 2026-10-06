# Voice Agent Studio

A multi-tenant voice AI agent platform: business units configure **knowledge, tools, skills and a persona**, and get an agent that **resolves** routine calls, **escalates** hard ones with a groundwork packet, and **learns** from every escalation by drafting fixes, proving them in simulated replays, and shipping them after human approval.

Demo domain: **Evergreen Health** (fictional health insurer) — Member Services and Pharmacy Benefits. All data is synthetic.

## Spec-driven development

`specs/` is an [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md) bundle and the **source of truth**. Every behavior change starts as a change proposal and spec edit, and specs ship in the same commit as code. Start with [`specs/index.md`](specs/index.md) and [`specs/process/sdd-workflow.md`](specs/process/sdd-workflow.md). Coding agents read [`AGENTS.md`](AGENTS.md).

```bash
git config core.hooksPath .githooks   # enable spec checks on commit
python scripts/spec_check.py          # lint the spec bundle
```

## Quick start

Prerequisites: Python 3.12 + [uv](https://docs.astral.sh/uv/), Node.js 22, a Groq API key (Deepgram key for voice).

```bash
cd apps/api && cp .env.example .env   # add GROQ_API_KEY, DEEPGRAM_API_KEY
uv sync && uv run voiceai serve       # API on http://localhost:8000 (auto-seeds demo data)

cd apps/web && npm install && npm run dev   # UI on http://localhost:3000
```

Details: [`specs/build/runbook-local.md`](specs/build/runbook-local.md) · Deploy to GCP: [`specs/build/runbook-gcp.md`](specs/build/runbook-gcp.md) · Demo: [`specs/product/demo-script.md`](specs/product/demo-script.md)
