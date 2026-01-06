# Terraform Backend Configuration
#
# This stores the Terraform state in a GCS bucket for team collaboration
# and CI/CD pipelines.
#
# FIRST TIME SETUP:
# 1. Create the bucket manually (one-time):
#    gsutil mb -l us-east1 gs://trust-engine-terraform-state
#    gsutil versioning set on gs://trust-engine-terraform-state
#
# 2. Initialize Terraform:
#    terraform init
#
# Note: The bucket must exist before running terraform init.
# State locking is automatic with GCS backend.

terraform {
  backend "gcs" {
    bucket = "trust-481601-terraform-state"
    prefix = "terraform/state"
  }
}

