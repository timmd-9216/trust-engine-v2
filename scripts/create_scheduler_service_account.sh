#!/usr/bin/env bash
# Script para crear el service account para Cloud Scheduler

set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 <project_id> [service_account_name]" >&2
  echo "" >&2
  echo "Example:" >&2
  echo "  $0 your-gcp-project-id scheduler" >&2
  echo "  $0 your-gcp-project-id cloud-scheduler-sa" >&2
  exit 1
fi

PROJECT_ID="$1"
SA_NAME="${2:-scheduler}"

SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "Creating service account: ${SA_EMAIL}"

# Check if service account already exists
if gcloud iam service-accounts describe "${SA_EMAIL}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Service account ${SA_EMAIL} already exists"
  exit 0
fi

# Create service account
gcloud iam service-accounts create "${SA_NAME}" \
  --project "${PROJECT_ID}" \
  --display-name="Cloud Scheduler Service Account" \
  --description="Service account for Cloud Scheduler to invoke Cloud Run services"

echo ""
echo "✓ Service account created: ${SA_EMAIL}"
echo ""
echo "Next step: Grant permissions to invoke Cloud Run services"
echo "  gcloud run services add-iam-policy-binding scrapping-tools \\"
echo "    --project ${PROJECT_ID} \\"
echo "    --region us-east1 \\"
echo "    --member=\"serviceAccount:${SA_EMAIL}\" \\"
echo "    --role=\"roles/run.invoker\""






