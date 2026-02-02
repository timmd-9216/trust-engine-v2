# Bootstrap API Enablement
#
# This file ensures that required GCP APIs are enabled before other resources
# that depend on them. The Cloud Resource Manager API is required for Terraform
# to manage project services, so it must be enabled first.
#
# Prerequisites:
#   - Service account must have 'roles/serviceusage.serviceUsageAdmin' role
#   - If Cloud Resource Manager API is completely disabled, you may need to
#     enable it manually via the GCP Console first:
#     https://console.developers.google.com/apis/api/cloudresourcemanager.googleapis.com/overview
#
# Permission Error?
#   If you see "Permission denied to list services", grant the service account:
#   gcloud projects add-iam-policy-binding PROJECT_ID \
#     --member="serviceAccount:SERVICE_ACCOUNT_EMAIL" \
#     --role="roles/serviceusage.serviceUsageAdmin"

# Enable Cloud Resource Manager API first (required for managing other APIs)
# Note: This API must be enabled manually via GCP Console if completely disabled:
# https://console.developers.google.com/apis/api/cloudresourcemanager.googleapis.com/overview?project=YOUR_PROJECT_ID
resource "google_project_service" "cloudresourcemanager" {
  project            = var.project_id
  service            = "cloudresourcemanager.googleapis.com"
  disable_on_destroy = false

  # This API is critical - don't disable it on destroy
  timeouts {
    create = "10m"
    update = "10m"
  }
}

