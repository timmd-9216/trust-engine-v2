# Terraform Backend Configuration
#
# The bucket is NOT set here (to avoid committing project-specific values).
# Configure it via one of these methods:
#
# 1. Backend config file (recommended for local dev):
#    cp backend.gcs.hcl.example backend.gcs.hcl
#    # Edit backend.gcs.hcl with your bucket name (file is gitignored)
#    terraform init -backend-config=backend.gcs.hcl
#
# 2. Inline flag:
#    terraform init -backend-config="bucket=YOUR_PROJECT_ID-terraform-state"
#
# 3. With GCP_PROJECT_ID:
#    terraform init -backend-config="bucket=${GCP_PROJECT_ID}-terraform-state"
#
# FIRST TIME: Create the bucket before init:
#   gsutil mb -l us-east1 gs://YOUR_PROJECT_ID-terraform-state
#   gsutil versioning set on gs://YOUR_PROJECT_ID-terraform-state

terraform {
  backend "gcs" {
    prefix = "terraform/state"
  }
}

