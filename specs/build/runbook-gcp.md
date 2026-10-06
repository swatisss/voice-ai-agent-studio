---
type: Runbook
title: GCP runbook
description: Build the single container and deploy it to Cloud Run with Secret Manager keys, optionally backed by Cloud SQL Postgres.
status: stable
tags: [build, runbook, gcp, cloud-run]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# One-time setup

```bash
gcloud auth login
gcloud config set project <PROJECT_ID>
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com
gcloud artifacts repositories create voiceai --repository-format=docker --location=us-central1
printf '%s' "$GROQ_API_KEY"       | gcloud secrets create GROQ_API_KEY --data-file=-
printf '%s' "$DEEPGRAM_API_KEY"   | gcloud secrets create DEEPGRAM_API_KEY --data-file=-
printf '%s' "$OPENROUTER_API_KEY" | gcloud secrets create OPENROUTER_API_KEY --data-file=-
```

Grant the Cloud Run runtime service account `roles/secretmanager.secretAccessor`.

# Deploy

```bash
PROJECT_ID=<PROJECT_ID> REGION=us-central1 ./infra/deploy-cloudrun.sh
```

The script builds `infra/Dockerfile` with Cloud Build, pushes to Artifact Registry and deploys service `voiceai` with the settings in [/architecture/deployment.md](/architecture/deployment.md) (1 instance, no CPU throttling, 3600 s timeout, session affinity, secrets as env vars). It prints the service URL.

# Optional: persistent database (Cloud SQL)

```bash
gcloud sql instances create voiceai-pg --database-version=POSTGRES_16 --tier=db-f1-micro --region=us-central1
gcloud sql databases create voiceai --instance=voiceai-pg
gcloud sql users create voiceai --instance=voiceai-pg --password=<PASSWORD>
DB_INSTANCE=<PROJECT_ID>:us-central1:voiceai-pg DB_PASSWORD=<PASSWORD> ./infra/deploy-cloudrun.sh
```

With `DB_INSTANCE` set, the script attaches the instance and sets `DATABASE_URL=postgresql+asyncpg://voiceai:<PASSWORD>@/voiceai?host=/cloudsql/<DB_INSTANCE>`.

# Verify

* `curl https://<url>/healthz` shows `status: ok` and the configured providers.
* Open the URL, pick a tenant, run Act 1 of the [demo script](/product/demo-script.md) in Type mode, then Talk mode.
