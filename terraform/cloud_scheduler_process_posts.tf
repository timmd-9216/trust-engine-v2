# Cloud Scheduler for Processing Posts
#
# Variables project_id and region are defined in variables.tf
#
# This scheduler is optional. Set enable_cloud_scheduler = true and provide
# the required variables to enable it.

variable "enable_cloud_scheduler" {
  description = "Enable Cloud Scheduler resources (set to false to disable)"
  type        = bool
  default     = false
}

variable "scrapping_tools_service_name" {
  description = "Name of the Cloud Run service for scrapping-tools (required if enable_cloud_scheduler = true)"
  type        = string
  default     = ""
}

variable "service_account_email" {
  description = "Service account email for OIDC authentication (required if enable_cloud_scheduler = true)"
  type        = string
  default     = ""
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

variable "process_jobs_job_name" {
  description = "Name of the Cloud Scheduler job for process-jobs"
  type        = string
  default     = "process-jobs-hourly"
}

variable "process_jobs_schedule" {
  description = "Cron schedule expression for process-jobs (default: every hour at minute 30)"
  type        = string
  default     = "30 * * * *"
}

variable "json_to_parquet_job_name" {
  description = "Name of the Cloud Scheduler job for json-to-parquet"
  type        = string
  default     = "json-to-parquet-daily"
}

variable "json_to_parquet_schedule" {
  description = "Cron schedule expression for json-to-parquet (default: daily at 7 AM UTC)"
  type        = string
  default     = "0 7 * * *"
}

# Provider is configured in versions.tf

# Enable Cloud Scheduler API
resource "google_project_service" "cloudscheduler" {
  count = var.enable_cloud_scheduler ? 1 : 0

  project            = var.project_id
  service            = "cloudscheduler.googleapis.com"
  disable_on_destroy = false
}

# Get Cloud Run service URL
data "google_cloud_run_service" "scrapping_tools" {
  count = var.enable_cloud_scheduler ? 1 : 0

  name     = var.scrapping_tools_service_name
  location = var.region
  project  = var.project_id

  depends_on = [google_project_service.cloudscheduler]
}

# Create Cloud Scheduler job
resource "google_cloud_scheduler_job" "process_posts" {
  count            = var.enable_cloud_scheduler ? 1 : 0
  name             = var.job_name
  description      = "Process posts hourly by calling /process-posts endpoint"
  schedule         = var.schedule
  time_zone        = var.time_zone
  region           = var.region
  attempt_deadline = "320s"

  http_target {
    uri         = "${data.google_cloud_run_service.scrapping_tools[0].status[0].url}/process-posts?max_posts=${var.max_posts}"
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
  value       = var.enable_cloud_scheduler ? google_cloud_scheduler_job.process_posts[0].name : null
}

output "scheduler_job_id" {
  description = "Full resource ID of the Cloud Scheduler job"
  value       = var.enable_cloud_scheduler ? google_cloud_scheduler_job.process_posts[0].id : null
}

output "endpoint_url" {
  description = "Full endpoint URL that will be called"
  value       = var.enable_cloud_scheduler ? "${data.google_cloud_run_service.scrapping_tools[0].status[0].url}/process-posts?max_posts=${var.max_posts}" : null
}

# Second scheduler for processing pending jobs
# Runs 30 minutes after process-posts (at minute 30 of every hour)
resource "google_cloud_scheduler_job" "process_jobs" {
  count            = var.enable_cloud_scheduler ? 1 : 0
  name             = var.process_jobs_job_name
  description      = "Process pending jobs by calling /process-jobs endpoint"
  schedule         = var.process_jobs_schedule
  time_zone        = var.time_zone
  region           = var.region
  attempt_deadline = "320s"

  http_target {
    uri         = "${data.google_cloud_run_service.scrapping_tools[0].status[0].url}/process-jobs"
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

output "process_jobs_scheduler_job_name" {
  description = "Name of the process-jobs Cloud Scheduler job"
  value       = var.enable_cloud_scheduler ? google_cloud_scheduler_job.process_jobs[0].name : null
}

output "process_jobs_scheduler_job_id" {
  description = "Full resource ID of the process-jobs Cloud Scheduler job"
  value       = var.enable_cloud_scheduler ? google_cloud_scheduler_job.process_jobs[0].id : null
}

output "process_jobs_endpoint_url" {
  description = "Full endpoint URL that will be called for process-jobs"
  value       = var.enable_cloud_scheduler ? "${data.google_cloud_run_service.scrapping_tools[0].status[0].url}/process-jobs" : null
}

# Third scheduler for converting JSONs to Parquet
# Runs daily at 7 AM UTC to convert new JSONs to Parquet format
resource "google_cloud_scheduler_job" "json_to_parquet" {
  count            = var.enable_cloud_scheduler ? 1 : 0
  name             = var.json_to_parquet_job_name
  description      = "Convert JSONs to Parquet format daily by calling /json-to-parquet endpoint"
  schedule         = var.json_to_parquet_schedule
  time_zone        = var.time_zone
  region           = var.region
  attempt_deadline = "600s" # 10 minutes - conversion can take longer

  http_target {
    uri         = "${data.google_cloud_run_service.scrapping_tools[0].status[0].url}/json-to-parquet"
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

output "json_to_parquet_scheduler_job_name" {
  description = "Name of the json-to-parquet Cloud Scheduler job"
  value       = var.enable_cloud_scheduler ? google_cloud_scheduler_job.json_to_parquet[0].name : null
}

output "json_to_parquet_scheduler_job_id" {
  description = "Full resource ID of the json-to-parquet Cloud Scheduler job"
  value       = var.enable_cloud_scheduler ? google_cloud_scheduler_job.json_to_parquet[0].id : null
}

output "json_to_parquet_endpoint_url" {
  description = "Full endpoint URL that will be called for json-to-parquet"
  value       = var.enable_cloud_scheduler ? "${data.google_cloud_run_service.scrapping_tools[0].status[0].url}/json-to-parquet" : null
}

