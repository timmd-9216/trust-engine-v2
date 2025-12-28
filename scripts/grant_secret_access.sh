#!/usr/bin/env bash
set -euo pipefail

# Script para otorgar permisos de Secret Manager a los service accounts necesarios

PROJECT_ID="${GCP_PROJECT_ID:-trust-481601}"
SECRET_NAME="INFORMATION_TRACER_API_KEY"

# Service account de GitHub Actions (para deployment)
GITHUB_ACTIONS_SA="ci-deployer@${PROJECT_ID}.iam.gserviceaccount.com"

# Service account de Cloud Run (para runtime)
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)")
CLOUD_RUN_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

echo "Granting Secret Manager access to service accounts..."
echo "Project: ${PROJECT_ID}"
echo "Secret: ${SECRET_NAME}"
echo ""

# Grant to GitHub Actions service account
echo "1. Granting access to GitHub Actions service account: ${GITHUB_ACTIONS_SA}"
gcloud secrets add-iam-policy-binding "${SECRET_NAME}" \
  --project="${PROJECT_ID}" \
  --member="serviceAccount:${GITHUB_ACTIONS_SA}" \
  --role="roles/secretmanager.secretAccessor"

echo "✓ GitHub Actions service account has access"
echo ""

# Grant to Cloud Run service account
echo "2. Granting access to Cloud Run service account: ${CLOUD_RUN_SA}"
gcloud secrets add-iam-policy-binding "${SECRET_NAME}" \
  --project="${PROJECT_ID}" \
  --member="serviceAccount:${CLOUD_RUN_SA}" \
  --role="roles/secretmanager.secretAccessor"

echo "✓ Cloud Run service account has access"
echo ""
echo "All service accounts now have access to the secret!"

