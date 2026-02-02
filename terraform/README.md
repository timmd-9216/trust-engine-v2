# Terraform Infrastructure

This directory contains Terraform configurations for the Trust Engine infrastructure.

## Files

| File | Description |
|------|-------------|
| `versions.tf` | Terraform and provider versions |
| `backend.tf` | GCS backend for remote state |
| `variables.tf` | Shared input variables |
| `bootstrap_apis.tf` | Bootstrap API enablement (Cloud Resource Manager) |
| `bigquery_external_tables.tf` | BigQuery dataset and external tables for analytics |
| `cloud_scheduler_process_posts.tf` | Cloud Scheduler jobs for automated processing |
| `workflow_nlp_process.tf` | Workflows and Eventarc for NLP processing |

## Prerequisites

1. **GCP Project** - The following APIs will be enabled automatically by Terraform:
   - Cloud Resource Manager API (enabled first via `bootstrap_apis.tf`)
   - BigQuery API (enabled automatically when creating BigQuery resources)
   - Cloud Scheduler API (enabled automatically when `enable_cloud_scheduler = true`)
   - Workflows API (enabled automatically when creating workflows)
   - Eventarc API (enabled automatically when creating triggers)
   - Cloud Run API (enabled automatically when referencing Cloud Run services)

   **Note**: If Cloud Resource Manager API is completely disabled, you may need to enable it manually first via the [GCP Console](https://console.developers.google.com/apis/api/cloudresourcemanager.googleapis.com/overview) before running Terraform.

2. **Terraform state bucket** (one-time setup):
   ```bash
   gsutil mb -l us-east1 gs://your-gcp-project-id-terraform-state
   gsutil versioning set on gs://your-gcp-project-id-terraform-state
   ```

3. **Service account** with necessary permissions:
   - BigQuery Admin
   - Cloud Scheduler Admin
   - Workflows Admin
   - Eventarc Admin

## Local Usage

### First time setup

```bash
cd terraform

# Copy and configure variables
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your values

# Configure backend (bucket is not in repo - use one of these):
# Option A: Backend config file (recommended)
cp backend.gcs.hcl.example backend.gcs.hcl
# Edit backend.gcs.hcl with your bucket name
terraform init -backend-config=backend.gcs.hcl

# Option B: Inline
terraform init -backend-config="bucket=YOUR_PROJECT_ID-terraform-state"
```

### Plan and Apply

```bash
# Preview changes
terraform plan

# Apply changes
terraform apply

# Destroy (be careful!)
terraform destroy
```

### Using command-line variables

```bash
terraform plan \
  -var="project_id=your-gcp-project-id" \
  -var="region=us-east1" \
  -var="gcs_bucket=trust-prd"
```

## GitHub Actions (CI/CD)

The Terraform workflow runs automatically:

| Event | Action |
|-------|--------|
| PR to `main` | `terraform plan` + comment on PR |
| Push to `main` | `terraform plan` + `terraform apply` |
| Manual dispatch | Choose: `plan`, `apply`, or `destroy` |

### Required Secrets/Variables

Set these in GitHub repository settings (Settings → Secrets and variables → Actions):

| Name | Type | Description |
|------|------|-------------|
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Secret | WIF provider for authentication |
| `GCP_SERVICE_ACCOUNT_EMAIL` | Secret | Service account for Terraform |
| `GCP_PROJECT_ID` | Variable | GCP project ID |
| `GCP_REGION` | Variable | GCP region (default: `us-east1`) |
| `GCS_BUCKET_NAME` | Variable | Bucket for data files |

### Service Account Permissions

The Terraform service account needs the following roles:

```bash
# Required for managing project services (enabling/disabling APIs)
gcloud projects add-iam-policy-binding your-gcp-project-id \
  --member="serviceAccount:ci-deployer@your-gcp-project-id.iam.gserviceaccount.com" \
  --role="roles/serviceusage.serviceUsageAdmin"

# Required for BigQuery resources
gcloud projects add-iam-policy-binding your-gcp-project-id \
  --member="serviceAccount:ci-deployer@your-gcp-project-id.iam.gserviceaccount.com" \
  --role="roles/bigquery.admin"

# Required for Cloud Scheduler resources
gcloud projects add-iam-policy-binding your-gcp-project-id \
  --member="serviceAccount:ci-deployer@your-gcp-project-id.iam.gserviceaccount.com" \
  --role="roles/cloudscheduler.admin"

# Required for Workflows resources
gcloud projects add-iam-policy-binding your-gcp-project-id \
  --member="serviceAccount:ci-deployer@your-gcp-project-id.iam.gserviceaccount.com" \
  --role="roles/workflows.admin"

# Required for Eventarc resources (if using workflows)
gcloud projects add-iam-policy-binding your-gcp-project-id \
  --member="serviceAccount:ci-deployer@your-gcp-project-id.iam.gserviceaccount.com" \
  --role="roles/eventarc.admin"

# For Terraform state bucket
gsutil iam ch \
  serviceAccount:ci-deployer@your-gcp-project-id.iam.gserviceaccount.com:objectAdmin \
  gs://your-gcp-project-id-terraform-state
```

**Important**: The `roles/serviceusage.serviceUsageAdmin` role is required for Terraform to enable/disable GCP APIs. Without this role, the bootstrap step will fail with a permission error.

## State Management

Terraform state is stored remotely in GCS:

- **Bucket**: `gs://your-gcp-project-id-terraform-state`
- **Prefix**: `terraform/state`
- **Locking**: Automatic with GCS

### View current state

```bash
terraform state list
terraform state show google_bigquery_dataset.analytics
```

### Import existing resources

```bash
terraform import google_bigquery_dataset.analytics your-gcp-project-id/trust_analytics
```

## BigQuery External Tables

After applying, query the external tables:

```sql
-- List all replies for a candidate
SELECT * 
FROM `your-gcp-project-id.trust_analytics.replies`
WHERE candidate_id = 'hnd01monc'
LIMIT 100;

-- Daily engagement summary
SELECT * 
FROM `your-gcp-project-id.trust_analytics.daily_engagement`
ORDER BY ingestion_date DESC;

-- Candidate totals
SELECT * 
FROM `your-gcp-project-id.trust_analytics.candidate_summary`;
```

## Troubleshooting

### "Backend initialization required"

```bash
terraform init -reconfigure
```

### "State lock"

If a previous run was interrupted:

```bash
terraform force-unlock LOCK_ID
```

### "Resource already exists"

Import it into state:

```bash
terraform import RESOURCE_ADDRESS RESOURCE_ID
```

### Validate configuration

```bash
terraform fmt -check -recursive
terraform validate
```

