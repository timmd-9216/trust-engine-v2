variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region for Workflows/Eventarc"
  type        = string
  default     = "us-east1"
}

variable "workflow_name" {
  description = "Name for the workflow"
  type        = string
  default     = "nlp-process-workflow"
}

variable "source_bucket" {
  description = "Bucket to watch for new objects"
  type        = string
}

variable "source_prefix" {
  description = "Optional object prefix to filter (e.g., path/inside/bucket/)"
  type        = string
  default     = ""
}

variable "output_bucket" {
  description = "Bucket where processed output will be written"
  type        = string
}

variable "nlp_process_url" {
  description = "HTTP endpoint for the nlp-process service"
  type        = string
}

provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_service_account" "workflow" {
  account_id   = "${var.workflow_name}-sa"
  display_name = "Workflow SA for ${var.workflow_name}"
}

resource "google_project_iam_member" "workflow_run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.workflow.email}"
}

resource "google_project_iam_member" "workflow_storage_viewer" {
  project = var.project_id
  role    = "roles/storage.objectViewer"
  member  = "serviceAccount:${google_service_account.workflow.email}"
}

resource "google_project_iam_member" "workflow_storage_creator" {
  project = var.project_id
  role    = "roles/storage.objectCreator"
  member  = "serviceAccount:${google_service_account.workflow.email}"
}

resource "google_project_iam_member" "workflow_invoker" {
  project = var.project_id
  role    = "roles/workflows.invoker"
  member  = "serviceAccount:${google_service_account.workflow.email}"
}

resource "google_workflows_workflow" "nlp_process" {
  name            = var.workflow_name
  region          = var.region
  service_account = google_service_account.workflow.email

  user_env_vars = {
    SOURCE_PREFIX      = var.source_prefix
    OUTPUT_BUCKET      = var.output_bucket
    NLP_PROCESS_URL    = var.nlp_process_url
    SOURCE_BUCKET_NAME = var.source_bucket
  }

  source_contents = <<-YAML
    main:
      params: [event]
      steps:
        - init:
            assign:
              - bucket: ${event["data"]["bucket"]}
              - object: ${event["data"]["name"]}
              - prefix: ${sys.get_env("SOURCE_PREFIX")}
              - source_bucket_env: ${sys.get_env("SOURCE_BUCKET_NAME")}
        - validate_bucket:
            switch:
              - condition: ${bucket != source_bucket_env}
                next: skip_wrong_bucket
        - check_prefix:
            switch:
              - condition: ${prefix != "" and not object.startsWith(prefix)}
                next: skip_prefix
        - check_extension:
            switch:
              - condition: ${not object.lower().endsWith(".csv")}
                next: skip_non_csv
        - call_nlp:
            call: http.post
            args:
              url: ${sys.get_env("NLP_PROCESS_URL")}
              auth:
                type: OIDC
              headers:
                Content-Type: application/json
              body:
                gcs_uri: ${"gs://" + bucket + "/" + object}
            result: nlp_response
        - serialize:
            assign:
              - output_content: ${json.encode_to_string(nlp_response.body)}
              - output_name: ${object + ".json"}
        - write_output:
            call: googleapis.storage.v1.objects.insert
            args:
              bucket: ${sys.get_env("OUTPUT_BUCKET")}
              name: ${output_name}
              media:
                mimeType: application/json
                data: ${output_content}
            result: storage_result
        - done:
            return:
              source: ${"gs://" + bucket + "/" + object}
              output: ${"gs://" + sys.get_env("OUTPUT_BUCKET") + "/" + output_name}
        - skip_non_csv:
            return:
              skipped: true
              reason: "Non-CSV object"
              object: ${object}
        - skip_prefix:
            return:
              skipped: true
              reason: "Prefix mismatch"
              object: ${object}
        - skip_wrong_bucket:
            return:
              skipped: true
              reason: "Bucket mismatch"
              object: ${object}
    YAML
}

resource "google_eventarc_trigger" "nlp_process" {
  name     = "${var.workflow_name}-trigger"
  location = var.region
  project  = var.project_id

  event_filters {
    attribute = "type"
    value     = "google.cloud.storage.object.v1.finalized"
  }

  event_filters {
    attribute = "bucket"
    value     = var.source_bucket
  }

  dynamic "event_filters" {
    for_each = var.source_prefix != "" ? [1] : []
    content {
      attribute = "objectNamePrefix"
      value     = var.source_prefix
    }
  }

  destination {
    workflow = google_workflows_workflow.nlp_process.id
  }

  service_account = google_service_account.workflow.email
}
