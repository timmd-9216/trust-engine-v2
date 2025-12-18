# Workload Identity Federation for GitHub Actions

This project uses Workload Identity Federation (WIF) to let GitHub Actions impersonate a Google Cloud service account without storing JSON keys.

## Required values (GitHub secrets/vars)
- `GCP_WORKLOAD_IDENTITY_PROVIDER`: e.g. `projects/123456789/locations/global/workloadIdentityPools/github-pool/providers/github-provider`
- `GCP_SERVICE_ACCOUNT_EMAIL`: e.g. `ci-deployer@PROJECT_ID.iam.gserviceaccount.com`
- `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_SERVICE_NAME`, `OPENROUTER_API_KEY`

## Minimal setup steps (gcloud)
```bash
PROJECT_ID=your-project
REGION=us-east1
POOL=github-pool
PROVIDER=github-provider
SA_NAME=ci-deployer
REPO="github.com/OWNER/REPO"   # adjust to this repo

gcloud iam service-accounts create $SA_NAME --project $PROJECT_ID
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/run.admin"
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.admin"
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"

gcloud iam workload-identity-pools create $POOL \
  --project=$PROJECT_ID --location="global" \
  --display-name="GitHub Actions Pool"

gcloud iam workload-identity-pools providers create-oidc $PROVIDER \
  --project=$PROJECT_ID --location="global" \
  --workload-identity-pool=$POOL \
  --display-name="GitHub Actions Provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --issuer-uri="https://token.actions.githubusercontent.com"

gcloud iam service-accounts add-iam-policy-binding "${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project=$PROJECT_ID \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_ID}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${REPO}" \
  --role="roles/iam.workloadIdentityUser"

gcloud iam service-accounts add-iam-policy-binding "${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project=$PROJECT_ID \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_ID}/locations/global/workloadIdentityPools/${POOL}/attribute.repository/${REPO}" \
  --role="roles/iam.workloadIdentityUser"

# Add Artifact Registry + Cloud Run roles to the deployer (project-level)
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/run.admin"
```

Then set the secrets in GitHub:
- `GCP_WORKLOAD_IDENTITY_PROVIDER`: output of `gcloud iam workload-identity-pools providers describe $PROVIDER ... --format='value(name)'`
- `GCP_SERVICE_ACCOUNT_EMAIL`: `${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com`

## Artifact Registry repo and permissions
Create the Docker repo (one-time):
```bash
gcloud artifacts repositories create cloud-run-source-deploy \
  --project $PROJECT_ID \
  --location us-east1 \
  --repository-format=docker \
  --description="Docker repo for Cloud Run deployments"
```

Grant the Cloud Build SA push access (used by `gcloud builds submit`):
```bash
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"
```

Ensure the deploy service account (used in GitHub Actions) also has Artifact Registry permissions (already covered above via `roles/artifactregistry.admin`).

## Troubleshooting WIF setup errors
- `INVALID_ARGUMENT: The attribute condition must reference one of the provider's claims`: avoid adding a condition when creating the provider; use the `--attribute-mapping` shown above and no `--attribute-condition`.
- `Identity Pool does not exist ... workloadIdentityPools/github-pool`: wait a few seconds after creating the pool before binding, or verify the pool name with `gcloud iam workload-identity-pools describe github-pool --location=global --project=$PROJECT_ID`.
- `Role roles/storage.objectViewer is not supported`: do not bind this role directly to the service account for WIF; instead, grant the needed project roles (e.g., `roles/artifactregistry.writer`, `roles/run.admin`) as shown above.

## Terraform sketch (adjust names)
```hcl
resource "google_service_account" "ci" {
  project      = var.project_id
  account_id   = "ci-deployer"
  display_name = "CI Deployer"
}

resource "google_workload_identity_pool" "github" {
  project      = var.project_id
  location     = "global"
  workload_identity_pool_id = "github-pool"
}

resource "google_workload_identity_pool_provider" "github_oidc" {
  project                    = var.project_id
  location                   = "global"
  workload_identity_pool_id  = google_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-provider"
  display_name               = "GitHub Actions"
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
  attribute_mapping = {
    "google.subject"     = "assertion.sub"
    "attribute.repository" = "assertion.repository"
  }
}

resource "google_service_account_iam_member" "ci_wif_user" {
  service_account_id = google_service_account.ci.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_workload_identity_pool.github.name}/attribute.repository/github.com/OWNER/REPO"
}

resource "google_project_iam_member" "ci_run_admin" {
  project = var.project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${google_service_account.ci.email}"
}

resource "google_project_iam_member" "ci_ar_admin" {
  project = var.project_id
  role    = "roles/artifactregistry.admin"
  member  = "serviceAccount:${google_service_account.ci.email}"
}
```
