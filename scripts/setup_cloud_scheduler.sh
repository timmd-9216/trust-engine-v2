#!/usr/bin/env bash
set -euo pipefail

# Script to set up Cloud Scheduler to call the /process-posts endpoint hourly with max_posts=10
#
# Usage:
#   ./scripts/setup_cloud_scheduler.sh <project_id> <region> <scrapping_tools_service_name> <service_account_email>
#
# Example:
#   ./scripts/setup_cloud_scheduler.sh trust-481601 us-east1 scrapping-tools scheduler@trust-481601.iam.gserviceaccount.com

require_env() {
  local name="$1"
  if [ -z "${!name:-}" ]; then
    echo "Missing required env var: $name" >&2
    exit 1
  fi
}

if [ $# -lt 4 ]; then
  echo "Usage: $0 <project_id> <region> <scrapping_tools_service_name> <service_account_email>" >&2
  echo "" >&2
  echo "Example:" >&2
  echo "  $0 trust-481601 us-east1 scrapping-tools scheduler@trust-481601.iam.gserviceaccount.com" >&2
  exit 1
fi

PROJECT_ID="$1"
REGION="$2"
SCRAPPING_TOOLS_SERVICE_NAME="$3"
SERVICE_ACCOUNT_EMAIL="$4"

# Verify Cloud Scheduler API is enabled
echo "Verifying Cloud Scheduler API is enabled..."
if ! gcloud services list --enabled --project "${PROJECT_ID}" --filter="name:cloudscheduler.googleapis.com" --format="value(name)" | grep -q "cloudscheduler.googleapis.com"; then
    echo "Cloud Scheduler API is not enabled. Enabling it..."
    gcloud services enable cloudscheduler.googleapis.com --project "${PROJECT_ID}"
    echo "Waiting for API to be enabled (this may take a minute)..."
    sleep 10
else
    echo "✓ Cloud Scheduler API is enabled"
fi

# Verify service account exists
echo "Verifying service account exists..."
if ! gcloud iam service-accounts describe "${SERVICE_ACCOUNT_EMAIL}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
    echo "Error: Service account '${SERVICE_ACCOUNT_EMAIL}' does not exist" >&2
    echo "" >&2
    echo "To create it, run:" >&2
    echo "  gcloud iam service-accounts create scheduler \\" >&2
    echo "    --project ${PROJECT_ID} \\" >&2
    echo "    --display-name=\"Cloud Scheduler Service Account\"" >&2
    echo "" >&2
    echo "Or use the default name:" >&2
    echo "  gcloud iam service-accounts create cloud-scheduler-sa \\" >&2
    echo "    --project ${PROJECT_ID} \\" >&2
    echo "    --display-name=\"Cloud Scheduler Service Account\"" >&2
    exit 1
else
    echo "✓ Service account exists"
fi

# Get the Cloud Run service URL
echo "Getting Cloud Run service URL..."
SERVICE_URL=$(gcloud run services describe "${SCRAPPING_TOOLS_SERVICE_NAME}" \
  --project "${PROJECT_ID}" \
  --region "${REGION}" \
  --format 'value(status.url)')

if [ -z "${SERVICE_URL}" ]; then
  echo "Error: Could not get service URL for ${SCRAPPING_TOOLS_SERVICE_NAME}" >&2
  exit 1
fi

ENDPOINT_URL="${SERVICE_URL}/process-posts?max_posts=10"
JOB_NAME="process-posts-hourly"
SCHEDULE="0 * * * *"  # Every hour at minute 0

echo "Setting up Cloud Scheduler job: ${JOB_NAME}"
echo "Project: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Endpoint: ${ENDPOINT_URL}"
echo "Schedule: ${SCHEDULE} (every hour, processing 10 posts)"
echo "Time Zone: UTC"
echo "Service Account: ${SERVICE_ACCOUNT_EMAIL}"
echo ""

# Check if job already exists
if gcloud scheduler jobs describe "${JOB_NAME}" \
  --project "${PROJECT_ID}" \
  --location "${REGION}" >/dev/null 2>&1; then
  echo "Job ${JOB_NAME} already exists. Updating..."
  gcloud scheduler jobs update http "${JOB_NAME}" \
    --project "${PROJECT_ID}" \
    --location "${REGION}" \
    --schedule "${SCHEDULE}" \
    --uri "${ENDPOINT_URL}" \
    --http-method POST \
    --oidc-service-account-email "${SERVICE_ACCOUNT_EMAIL}" \
    --time-zone "UTC"
else
  echo "Creating new job ${JOB_NAME}..."
  gcloud scheduler jobs create http "${JOB_NAME}" \
    --project "${PROJECT_ID}" \
    --location "${REGION}" \
    --schedule "${SCHEDULE}" \
    --uri "${ENDPOINT_URL}" \
    --http-method POST \
    --oidc-service-account-email "${SERVICE_ACCOUNT_EMAIL}" \
    --time-zone "UTC"
fi

echo ""
echo "✓ Cloud Scheduler job configured successfully!"
echo ""
echo "To manually trigger the job:"
echo "  gcloud scheduler jobs run ${JOB_NAME} --project ${PROJECT_ID} --location ${REGION}"
echo ""
echo "To view job details:"
echo "  gcloud scheduler jobs describe ${JOB_NAME} --project ${PROJECT_ID} --location ${REGION}"
echo ""
echo "To delete the job:"
echo "  gcloud scheduler jobs delete ${JOB_NAME} --project ${PROJECT_ID} --location ${REGION}"

