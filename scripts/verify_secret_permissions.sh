#!/usr/bin/env bash
set -euo pipefail

# Script para verificar los permisos del secreto INFORMATION_TRACER_API_KEY

PROJECT_ID="${GCP_PROJECT_ID:-trust-481601}"
SECRET_NAME="INFORMATION_TRACER_API_KEY"

echo "Checking IAM policy for secret: ${SECRET_NAME}"
echo "Project: ${PROJECT_ID}"
echo ""

gcloud secrets get-iam-policy "${SECRET_NAME}" \
  --project="${PROJECT_ID}"

echo ""
echo "Expected members:"
echo "- serviceAccount:ci-deployer@${PROJECT_ID}.iam.gserviceaccount.com (GitHub Actions)"
echo "- serviceAccount:127336238226-compute@developer.gserviceaccount.com (Cloud Run)"
echo ""
echo "Both should have role: roles/secretmanager.secretAccessor"

