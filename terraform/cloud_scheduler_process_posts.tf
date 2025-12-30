variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region for Cloud Scheduler"
  type        = string
  default     = "us-east1"
}

variable "scrapping_tools_service_name" {
  description = "Name of the Cloud Run service for scrapping-tools"
  type        = string
}

variable "service_account_email" {
  description = "Service account email for OIDC authentication"
  type        = string
}

variable "max_posts" {
  description = "Maximum number of posts to process per execution"
  type        = number
  default     = 10
}

variable "schedule" {
  description = "Cron schedule expression (default: every hour at minute 0)"
  type        = string
  default     = "0 * * * *"
}

variable "job_name" {
  description = "Name of the Cloud Scheduler job"
  type        = string
  default     = "process-posts-hourly"
}

variable "time_zone" {
  description = "Time zone for the schedule"
  type        = string
  default     = "UTC"
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# Enable Cloud Scheduler API
resource "google_project_service" "cloudscheduler" {
  project            = var.project_id
  service            = "cloudscheduler.googleapis.com"
  disable_on_destroy = false
}

# Get Cloud Run service URL
data "google_cloud_run_service" "scrapping_tools" {
  name     = var.scrapping_tools_service_name
  location = var.region
  project  = var.project_id

  depends_on = [google_project_service.cloudscheduler]
}

# Create Cloud Scheduler job
resource "google_cloud_scheduler_job" "process_posts" {
  name             = var.job_name
  description      = "Process posts hourly by calling /process-posts endpoint"
  schedule         = var.schedule
  time_zone        = var.time_zone
  region           = var.region
  attempt_deadline = "320s"

  http_target {
    uri         = "${data.google_cloud_run_service.scrapping_tools.status.url}/process-posts?max_posts=${var.max_posts}"
    http_method = "POST"

    oidc_token {
      service_account_email = var.service_account_email
    }
  }

  depends_on = [
    google_project_service.cloudscheduler,
    data.google_cloud_run_service.scrapping_tools,
  ]
}

output "scheduler_job_name" {
  description = "Name of the created Cloud Scheduler job"
  value       = google_cloud_scheduler_job.process_posts.name
}

output "scheduler_job_id" {
  description = "Full resource ID of the Cloud Scheduler job"
  value       = google_cloud_scheduler_job.process_posts.id
}

output "endpoint_url" {
  description = "Full endpoint URL that will be called"
  value       = "${data.google_cloud_run_service.scrapping_tools.status.url}/process-posts?max_posts=${var.max_posts}"
}

