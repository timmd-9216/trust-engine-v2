# Shared Variables for all Terraform configurations
#
# These variables are used across all .tf files in this directory.
# Set values via:
#   - terraform.tfvars file (gitignored, for local development)
#   - -var flags on command line
#   - TF_VAR_* environment variables (used in CI/CD)

variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region for resources"
  type        = string
  default     = "us-east1"
}

variable "gcs_bucket" {
  description = "GCS bucket name for data (used by BigQuery external tables)"
  type        = string
  default     = ""
}

variable "environment" {
  description = "Environment name (e.g., dev, staging, prod)"
  type        = string
  default     = "prod"
}

