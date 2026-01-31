#!/usr/bin/env bash
# Update the process-jobs-hourly Cloud Scheduler job URI (e.g. to change max_jobs).
# Loads PROJECT_ID, REGION and optional SERVICE_NAME from .env; gets SERVICE_URL via gcloud.
#
# Usage:
#   ./scripts/update_scheduler_process_jobs_uri.sh [max_jobs]
#   Default max_jobs=20 if not given.
#
# Requires in .env (or export before running):
#   GCP_PROJECT_ID
#   GCP_REGION
#   Optional: SCRAPPING_TOOLS_SERVICE_NAME (default: scrapping-tools)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/.env"

if [ -f "${ENV_FILE}" ]; then
  set -a
  # shellcheck source=/dev/null
  source "${ENV_FILE}"
  set +a
fi

PROJECT_ID="${GCP_PROJECT_ID:-}"
REGION="${GCP_REGION:-}"
SERVICE_NAME="${SCRAPPING_TOOLS_SERVICE_NAME:-scrapping-tools}"
MAX_JOBS="${1:-20}"

if [ -z "${PROJECT_ID}" ]; then
  echo "Error: GCP_PROJECT_ID not set. Set it in .env or export it." >&2
  exit 1
fi
if [ -z "${REGION}" ]; then
  echo "Error: GCP_REGION not set. Set it in .env or export it." >&2
  exit 1
fi

echo "Getting Cloud Run service URL for ${SERVICE_NAME}..."
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --format 'value(status.url)')

if [ -z "${SERVICE_URL}" ]; then
  echo "Error: Could not get service URL." >&2
  exit 1
fi

NEW_URI="${SERVICE_URL}/process-jobs?max_jobs=${MAX_JOBS}"
echo "Updating process-jobs-hourly to: ${NEW_URI}"

gcloud scheduler jobs update http process-jobs-hourly \
  --project "${PROJECT_ID}" \
  --location "${REGION}" \
  --uri "${NEW_URI}"

echo "Done."
