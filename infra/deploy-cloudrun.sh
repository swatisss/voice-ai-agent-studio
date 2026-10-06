#!/usr/bin/env bash
# Build with Cloud Build and deploy the single voiceai service to Cloud Run.
# Spec: /build/runbook-gcp.md, /architecture/deployment.md
#
# Usage:  PROJECT_ID=my-proj REGION=us-central1 ./infra/deploy-cloudrun.sh
# Optional persistent DB:  DB_INSTANCE=my-proj:us-central1:voiceai-pg DB_PASSWORD=... ./infra/deploy-cloudrun.sh
set -euo pipefail

: "${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-voiceai}"
REPO="${REPO:-voiceai}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE}:$(date +%Y%m%d-%H%M%S)"

cd "$(dirname "$0")/.."

echo "==> Building ${IMAGE}"
BUILD_CFG="$(mktemp)"
trap 'rm -f "${BUILD_CFG}"' EXIT
cat > "${BUILD_CFG}" <<EOF
steps:
  - name: gcr.io/cloud-builders/docker
    args: ["build", "-f", "infra/Dockerfile", "-t", "${IMAGE}", "."]
images: ["${IMAGE}"]
timeout: 1800s
EOF
gcloud builds submit --project "${PROJECT_ID}" --region "${REGION}" --config "${BUILD_CFG}" .

ENV_VARS="AUTO_SEED=1,JOBS_ENABLED=1,CORS_ORIGINS="
EXTRA=()
if [[ -n "${DB_INSTANCE:-}" ]]; then
  : "${DB_PASSWORD:?set DB_PASSWORD when DB_INSTANCE is set}"
  ENV_VARS+=",DATABASE_URL=postgresql+asyncpg://voiceai:${DB_PASSWORD}@/voiceai?host=/cloudsql/${DB_INSTANCE}"
  EXTRA+=(--add-cloudsql-instances "${DB_INSTANCE}")
fi

echo "==> Deploying ${SERVICE} to ${REGION}"
gcloud run deploy "${SERVICE}" --project "${PROJECT_ID}" --region "${REGION}" \
  --image "${IMAGE}" --platform managed --allow-unauthenticated \
  --min-instances 1 --max-instances 1 --no-cpu-throttling \
  --cpu 2 --memory 2Gi --timeout 3600 --session-affinity \
  --set-env-vars "${ENV_VARS}" \
  --set-secrets "GROQ_API_KEY=GROQ_API_KEY:latest,DEEPGRAM_API_KEY=DEEPGRAM_API_KEY:latest,OPENROUTER_API_KEY=OPENROUTER_API_KEY:latest" \
  "${EXTRA[@]}"

URL="$(gcloud run services describe "${SERVICE}" --project "${PROJECT_ID}" --region "${REGION}" --format 'value(status.url)')"
echo "==> Deployed: ${URL}"
curl -fsS "${URL}/healthz" && echo
