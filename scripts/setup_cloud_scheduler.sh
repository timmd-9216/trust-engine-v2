#!/usr/bin/env bash
set -euo pipefail

# Script to set up Cloud Scheduler jobs for both /process-posts and /process-jobs endpoints
# Creates two schedulers:
#   1. process-posts-hourly: Runs every 30 minutes at minutes 0 and 30, calls /process-posts?max_posts_to_process=10
#   2. process-jobs-hourly: Runs every 30 minutes at minutes 15 and 45, calls /process-jobs (processes all pending jobs)
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

# ============================================================================
# Scheduler 1: process-posts-hourly
# ============================================================================
ENDPOINT_URL="${SERVICE_URL}/process-posts?max_posts_to_process=10"
JOB_NAME="process-posts-hourly"
SCHEDULE="0,30 * * * *"  # Every 30 minutes at minutes 0 and 30

echo "=========================================="
echo "Setting up Cloud Scheduler job: ${JOB_NAME}"
echo "=========================================="
echo "Project: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Endpoint: ${ENDPOINT_URL}"
echo "Schedule: ${SCHEDULE} (every 30 minutes at minutes 0 and 30, processing 10 posts)"
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

echo "✓ Cloud Scheduler job '${JOB_NAME}' configured successfully!"
echo ""

# ============================================================================
# Scheduler 2: process-jobs-hourly
# ============================================================================
PROCESS_JOBS_ENDPOINT_URL="${SERVICE_URL}/process-jobs"
PROCESS_JOBS_JOB_NAME="process-jobs-hourly"
PROCESS_JOBS_SCHEDULE="15,45 * * * *"  # Every 30 minutes at minutes 15 and 45

echo "=========================================="
echo "Setting up Cloud Scheduler job: ${PROCESS_JOBS_JOB_NAME}"
echo "=========================================="
echo "Project: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Endpoint: ${PROCESS_JOBS_ENDPOINT_URL}"
echo "Schedule: ${PROCESS_JOBS_SCHEDULE} (every 30 minutes at minutes 15 and 45, processes all pending jobs)"
echo "Time Zone: UTC"
echo "Service Account: ${SERVICE_ACCOUNT_EMAIL}"
echo ""

# Check if job already exists
if gcloud scheduler jobs describe "${PROCESS_JOBS_JOB_NAME}" \
  --project "${PROJECT_ID}" \
  --location "${REGION}" >/dev/null 2>&1; then
  echo "Job ${PROCESS_JOBS_JOB_NAME} already exists. Updating..."
  gcloud scheduler jobs update http "${PROCESS_JOBS_JOB_NAME}" \
    --project "${PROJECT_ID}" \
    --location "${REGION}" \
    --schedule "${PROCESS_JOBS_SCHEDULE}" \
    --uri "${PROCESS_JOBS_ENDPOINT_URL}" \
    --http-method POST \
    --oidc-service-account-email "${SERVICE_ACCOUNT_EMAIL}" \
    --time-zone "UTC"
else
  echo "Creating new job ${PROCESS_JOBS_JOB_NAME}..."
  gcloud scheduler jobs create http "${PROCESS_JOBS_JOB_NAME}" \
    --project "${PROJECT_ID}" \
    --location "${REGION}" \
    --schedule "${PROCESS_JOBS_SCHEDULE}" \
    --uri "${PROCESS_JOBS_ENDPOINT_URL}" \
    --http-method POST \
    --oidc-service-account-email "${SERVICE_ACCOUNT_EMAIL}" \
    --time-zone "UTC"
fi

echo "✓ Cloud Scheduler job '${PROCESS_JOBS_JOB_NAME}' configured successfully!"
echo ""

# ============================================================================
# Scheduler 3: json-to-parquet-daily
# ============================================================================
JSON_TO_PARQUET_ENDPOINT_URL="${SERVICE_URL}/json-to-parquet?skip_timestamp_filter=false"
JSON_TO_PARQUET_JOB_NAME="json-to-parquet-daily"
JSON_TO_PARQUET_SCHEDULE="0 7 * * *"  # Daily at 7 AM UTC

echo "=========================================="
echo "Setting up Cloud Scheduler job: ${JSON_TO_PARQUET_JOB_NAME}"
echo "=========================================="
echo "Project: ${PROJECT_ID}"
echo "Region: ${REGION}"
echo "Endpoint: ${JSON_TO_PARQUET_ENDPOINT_URL}"
echo "Schedule: ${JSON_TO_PARQUET_SCHEDULE} (daily at 7 AM UTC)"
echo "Time Zone: UTC"
echo "Service Account: ${SERVICE_ACCOUNT_EMAIL}"
echo ""

# Check if job already exists
if gcloud scheduler jobs describe "${JSON_TO_PARQUET_JOB_NAME}" \
  --project "${PROJECT_ID}" \
  --location "${REGION}" >/dev/null 2>&1; then
  echo "Job ${JSON_TO_PARQUET_JOB_NAME} already exists. Updating..."
  gcloud scheduler jobs update http "${JSON_TO_PARQUET_JOB_NAME}" \
    --project "${PROJECT_ID}" \
    --location "${REGION}" \
    --schedule "${JSON_TO_PARQUET_SCHEDULE}" \
    --uri "${JSON_TO_PARQUET_ENDPOINT_URL}" \
    --http-method POST \
    --oidc-service-account-email "${SERVICE_ACCOUNT_EMAIL}" \
    --time-zone "UTC" \
    --attempt-deadline 600s
else
  echo "Creating new job ${JSON_TO_PARQUET_JOB_NAME}..."
  gcloud scheduler jobs create http "${JSON_TO_PARQUET_JOB_NAME}" \
    --project "${PROJECT_ID}" \
    --location "${REGION}" \
    --schedule "${JSON_TO_PARQUET_SCHEDULE}" \
    --uri "${JSON_TO_PARQUET_ENDPOINT_URL}" \
    --http-method POST \
    --oidc-service-account-email "${SERVICE_ACCOUNT_EMAIL}" \
    --time-zone "UTC" \
    --attempt-deadline 600s \
    --description="Convert JSONs to Parquet format daily by calling /json-to-parquet endpoint"
fi

echo "✓ Cloud Scheduler job '${JSON_TO_PARQUET_JOB_NAME}' configured successfully!"
echo ""

# ============================================================================
# Summary
# ============================================================================
echo "=========================================="
echo "✓ All Cloud Scheduler jobs configured successfully!"
echo "=========================================="
echo ""
echo "Jobs created:"
echo "  1. ${JOB_NAME} - Runs every 30 minutes at :00 and :30"
echo "  2. ${PROCESS_JOBS_JOB_NAME} - Runs every 30 minutes at :15 and :45"
echo "  3. ${JSON_TO_PARQUET_JOB_NAME} - Runs daily at 7 AM UTC"
echo ""
echo "To manually trigger the jobs:"
echo "  gcloud scheduler jobs run ${JOB_NAME} --project ${PROJECT_ID} --location ${REGION}"
echo "  gcloud scheduler jobs run ${PROCESS_JOBS_JOB_NAME} --project ${PROJECT_ID} --location ${REGION}"
echo "  gcloud scheduler jobs run ${JSON_TO_PARQUET_JOB_NAME} --project ${PROJECT_ID} --location ${REGION}"
echo ""
echo "To view job details:"
echo "  gcloud scheduler jobs describe ${JOB_NAME} --project ${PROJECT_ID} --location ${REGION}"
echo "  gcloud scheduler jobs describe ${PROCESS_JOBS_JOB_NAME} --project ${PROJECT_ID} --location ${REGION}"
echo "  gcloud scheduler jobs describe ${JSON_TO_PARQUET_JOB_NAME} --project ${PROJECT_ID} --location ${REGION}"
echo ""
echo "To delete the jobs:"
echo "  gcloud scheduler jobs delete ${JOB_NAME} --project ${PROJECT_ID} --location ${REGION}"
echo "  gcloud scheduler jobs delete ${PROCESS_JOBS_JOB_NAME} --project ${PROJECT_ID} --location ${REGION}"
echo "  gcloud scheduler jobs delete ${JSON_TO_PARQUET_JOB_NAME} --project ${PROJECT_ID} --location ${REGION}"

