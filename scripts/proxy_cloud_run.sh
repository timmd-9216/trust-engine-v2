#!/usr/bin/env bash
set -euo pipefail

# Proxy a Cloud Run service locally using gcloud run services proxy.
# Expects environment variables (use .env or export manually):
#   GCP_PROJECT_ID
#   GCP_REGION
#   GCP_SERVICE_NAME
# Optional:
#   PROXY_PORT (default 8080)
#
# Example:
#   source .env
#   ./scripts/proxy_cloud_run.sh

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

PROXY_PORT="${PROXY_PORT:-8080}"

echo "Starting proxy for service ${GCP_SERVICE_NAME} in project ${GCP_PROJECT_ID}, region ${GCP_REGION} on localhost:${PROXY_PORT}..."
gcloud run services proxy "${GCP_SERVICE_NAME}" \
  --project "${GCP_PROJECT_ID}" \
  --region "${GCP_REGION}" \
  --port "${PROXY_PORT}"
