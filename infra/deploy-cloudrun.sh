#!/usr/bin/env bash
# Build with Cloud Build and deploy the single voiceai service to Cloud Run.
# Spec: /build/runbook-gcp.md, /architecture/deployment.md
#
# Usage:  PROJECT_ID=my-proj REGION=us-central1 ./infra/deploy-cloudrun.sh
# Optional persistent DB:  DB_INSTANCE=my-proj:us-central1:voiceai-pg DB_PASSWORD=... ./infra/deploy-cloudrun.sh
# Phone calls:  PUBLIC_BASE_URL=https://<service-url> (must equal the URL Twilio calls); secrets TWILIO_AUTH_TOKEN, TWILIO_ACCOUNT_SID
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
if [[ -n "${PUBLIC_BASE_URL:-}" ]]; then
  ENV_VARS+=",PUBLIC_BASE_URL=${PUBLIC_BASE_URL%/}"
fi
EXTRA=()
if [[ -n "${DB_INSTANCE:-}" ]]; then
  : "${DB_PASSWORD:?set DB_PASSWORD when DB_INSTANCE is set}"
  ENV_VARS+=",DATABASE_URL=postgresql+asyncpg://voiceai:${DB_PASSWORD}@/voiceai?host=/cloudsql/${DB_INSTANCE}"
  EXTRA+=(--add-cloudsql-instances "${DB_INSTANCE}")
fi

# GROQ and DEEPGRAM are required; the others are optional and attached only when the secret exists
# (OPENAI_API_KEY is needed by realtime agents, the TWILIO_* secrets by phone calls).
SECRETS="GROQ_API_KEY=GROQ_API_KEY:latest,DEEPGRAM_API_KEY=DEEPGRAM_API_KEY:latest"
for optional in OPENROUTER_API_KEY OPENAI_API_KEY TWILIO_AUTH_TOKEN TWILIO_ACCOUNT_SID; do
  if gcloud secrets describe "${optional}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
    SECRETS+=",${optional}=${optional}:latest"
  else
    echo "==> Optional secret ${optional} not found in Secret Manager; deploying without it"
  fi
done

echo "==> Deploying ${SERVICE} to ${REGION}"
gcloud run deploy "${SERVICE}" --project "${PROJECT_ID}" --region "${REGION}" \
  --image "${IMAGE}" --platform managed --allow-unauthenticated \
  --min-instances 1 --max-instances 1 --no-cpu-throttling \
  --cpu 2 --memory 2Gi --timeout 3600 --session-affinity \
  --set-env-vars "${ENV_VARS}" \
  --set-secrets "${SECRETS}" \
  "${EXTRA[@]}"

URL="$(gcloud run services describe "${SERVICE}" --project "${PROJECT_ID}" --region "${REGION}" --format 'value(status.url)')"
echo "==> Deployed: ${URL}"
curl -fsS "${URL}/healthz" && echo
