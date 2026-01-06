# Terraform Infrastructure

This directory contains Terraform configurations for the Trust Engine infrastructure.

## Files

| File | Description |
|------|-------------|
| `versions.tf` | Terraform and provider versions |
| `backend.tf` | GCS backend for remote state |
| `variables.tf` | Shared input variables |
| `bigquery_external_tables.tf` | BigQuery dataset and external tables for analytics |
| `cloud_scheduler_process_posts.tf` | Cloud Scheduler jobs for automated processing |
| `workflow_nlp_process.tf` | Workflows and Eventarc for NLP processing |

## Prerequisites

1. **GCP Project** with the following APIs enabled:
   - Cloud Resource Manager API
   - BigQuery API
   - Cloud Scheduler API
   - Workflows API
   - Eventarc API
   - Cloud Run API

2. **Terraform state bucket** (one-time setup):
   ```bash
   gsutil mb -l us-east1 gs://trust-engine-terraform-state
   gsutil versioning set on gs://trust-engine-terraform-state
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

# Initialize Terraform
terraform init
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
  -var="project_id=trust-481601" \
  -var="region=us-east1" \
  -var="gcs_bucket=trust-engine-data"
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

The Terraform service account needs:

```bash
# Grant roles to service account
gcloud projects add-iam-policy-binding trust-481601 \
  --member="serviceAccount:ci-deployer@trust-481601.iam.gserviceaccount.com" \
  --role="roles/bigquery.admin"

gcloud projects add-iam-policy-binding trust-481601 \
  --member="serviceAccount:ci-deployer@trust-481601.iam.gserviceaccount.com" \
  --role="roles/cloudscheduler.admin"

gcloud projects add-iam-policy-binding trust-481601 \
  --member="serviceAccount:ci-deployer@trust-481601.iam.gserviceaccount.com" \
  --role="roles/workflows.admin"

# For state bucket
gsutil iam ch \
  serviceAccount:ci-deployer@trust-481601.iam.gserviceaccount.com:objectAdmin \
  gs://trust-engine-terraform-state
```

## State Management

Terraform state is stored remotely in GCS:

- **Bucket**: `gs://trust-engine-terraform-state`
- **Prefix**: `terraform/state`
- **Locking**: Automatic with GCS

### View current state

```bash
terraform state list
terraform state show google_bigquery_dataset.analytics
```

### Import existing resources

```bash
terraform import google_bigquery_dataset.analytics trust-481601/trust_analytics
```

## BigQuery External Tables

After applying, query the external tables:

```sql
-- List all replies for a candidate
SELECT * 
FROM `trust-481601.trust_analytics.replies`
WHERE candidate_id = 'hnd01monc'
LIMIT 100;

-- Daily engagement summary
SELECT * 
FROM `trust-481601.trust_analytics.daily_engagement`
ORDER BY ingestion_date DESC;

-- Candidate totals
SELECT * 
FROM `trust-481601.trust_analytics.candidate_summary`;
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

