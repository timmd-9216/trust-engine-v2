#!/usr/bin/env bash
set -euo pipefail

# Build container image with Cloud Build and deploy to Cloud Run.
# Requires: gcloud CLI authenticated, Artifact Registry repo created,
# and env vars: GCP_PROJECT_ID, GCP_REGION, GCP_SERVICE_NAME.
# Optional envs:
# - TAG: image tag (defaults to git short SHA or timestamp)
# - AR_REPO: Artifact Registry repo name (defaults to cloud-run-source-deploy)
# - OPENROUTER_API_KEY: passed to Cloud Run if set
# - CLOUD_RUN_ENV_VARS: extra env vars string for --set-env-vars (e.g. "KEY=VALUE,KEY2=VALUE2")

require_env() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    echo "Missing required env var: $name" >&2
    exit 1
  fi
}

require_env GCP_PROJECT_ID
require_env GCP_REGION
require_env GCP_SERVICE_NAME

TAG="${TAG:-$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M)}"
AR_REPO="${AR_REPO:-cloud-run-source-deploy}"
REPO_PATH="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/${AR_REPO}"
IMAGE="${REPO_PATH}/${GCP_SERVICE_NAME}:${TAG}"

echo "Building with Cloud Build (no local Docker needed)..."
gcloud builds submit --project "${GCP_PROJECT_ID}" --tag "${IMAGE}"

echo "Deploying to Cloud Run..."
# Build env var arguments from provided environment
ENV_ARGS=()
if [ -n "${OPENROUTER_API_KEY:-}" ]; then
  ENV_ARGS+=(--set-env-vars "OPENROUTER_API_KEY=${OPENROUTER_API_KEY}")
fi
if [ -n "${CLOUD_RUN_ENV_VARS:-}" ]; then
  ENV_ARGS+=(--set-env-vars "${CLOUD_RUN_ENV_VARS}")
fi

gcloud run deploy "${GCP_SERVICE_NAME}" \
  --project "${GCP_PROJECT_ID}" \
  --region "${GCP_REGION}" \
  --image "${IMAGE}" \
  --platform managed \
  --allow-unauthenticated \
  "${ENV_ARGS[@]}" \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --max-instances 10 \
  --min-instances 0 \
  --port 8080

echo "Done. Deployed image: ${IMAGE}"
