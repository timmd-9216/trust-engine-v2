# BigQuery External Tables for Analytics
#
# This Terraform configuration creates BigQuery external tables
# that read Parquet files from GCS for analytics.
#
# Prerequisites:
#   - GCS bucket with processed Parquet files
#   - Run json_to_parquet.py to generate Parquet files first
#
# Usage:
#   cd terraform
#   terraform init
#   terraform plan
#   terraform apply

variable "bigquery_dataset" {
  description = "BigQuery dataset name for analytics tables"
  type        = string
  default     = "trust_analytics"
}

# Create BigQuery dataset
resource "google_bigquery_dataset" "analytics" {
  dataset_id  = var.bigquery_dataset
  project     = var.project_id
  location    = var.region

  description = "Trust Engine analytics dataset with external tables on GCS Parquet files"

  labels = {
    environment = "production"
    managed_by  = "terraform"
  }
}

# External table for Twitter/Instagram replies
resource "google_bigquery_table" "replies" {
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  project    = var.project_id
  table_id   = "replies"

  description = "External table for social media replies stored as Parquet in GCS"

  external_data_configuration {
    autodetect    = true
    source_format = "PARQUET"
    source_uris   = ["gs://${var.gcs_bucket}/processed/replies/*"]

    hive_partitioning_options {
      mode                     = "AUTO"
      source_uri_prefix        = "gs://${var.gcs_bucket}/processed/replies/"
      require_partition_filter = false
    }
  }

  labels = {
    data_source = "information_tracer"
    layer       = "processed"
  }

  deletion_protection = false
}

# View for Twitter replies only
resource "google_bigquery_table" "twitter_replies" {
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  project    = var.project_id
  table_id   = "twitter_replies"

  description = "View for Twitter replies only"

  view {
    query          = <<-SQL
      SELECT *
      FROM `${var.project_id}.${var.bigquery_dataset}.replies`
      WHERE platform = 'twitter'
    SQL
    use_legacy_sql = false
  }

  depends_on = [google_bigquery_table.replies]

  deletion_protection = false
}

# View for Instagram replies only
resource "google_bigquery_table" "instagram_replies" {
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  project    = var.project_id
  table_id   = "instagram_replies"

  description = "View for Instagram replies only"

  view {
    query          = <<-SQL
      SELECT *
      FROM `${var.project_id}.${var.bigquery_dataset}.replies`
      WHERE platform = 'instagram'
    SQL
    use_legacy_sql = false
  }

  depends_on = [google_bigquery_table.replies]

  deletion_protection = false
}

# Aggregate view: daily engagement by candidate
resource "google_bigquery_table" "daily_engagement" {
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  project    = var.project_id
  table_id   = "daily_engagement"

  description = "Daily engagement metrics aggregated by candidate"

  view {
    query          = <<-SQL
      SELECT
        ingestion_date,
        country,
        platform,
        candidate_id,
        COUNT(*) as total_replies,
        COUNT(DISTINCT parent_post_id) as posts_with_replies,
        COUNT(DISTINCT COALESCE(user_screen_name, username, '')) as unique_users,
        SUM(COALESCE(favorite_count, like_count, 0)) as total_favorites,
        SUM(COALESCE(retweet_count, 0)) as total_retweets,
        SUM(COALESCE(reply_count, 0)) as total_reply_count,
        AVG(COALESCE(favorite_count, like_count, 0)) as avg_favorites_per_reply,
        SUM(CASE WHEN COALESCE(is_retweet, false) THEN 1 ELSE 0 END) as retweet_replies,
        SUM(CASE WHEN COALESCE(is_quote_status, false) THEN 1 ELSE 0 END) as quote_replies,
        SUM(CASE WHEN COALESCE(has_media, false) THEN 1 ELSE 0 END) as replies_with_media
      FROM `${var.project_id}.${var.bigquery_dataset}.replies`
      GROUP BY ingestion_date, country, platform, candidate_id
      ORDER BY ingestion_date DESC, candidate_id
    SQL
    use_legacy_sql = false
  }

  depends_on = [google_bigquery_table.replies]

  deletion_protection = false
}

# Aggregate view: candidate summary
resource "google_bigquery_table" "candidate_summary" {
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  project    = var.project_id
  table_id   = "candidate_summary"

  description = "Overall summary metrics by candidate"

  view {
    query          = <<-SQL
      SELECT
        country,
        platform,
        candidate_id,
        COUNT(*) as total_replies,
        COUNT(DISTINCT parent_post_id) as total_posts_analyzed,
        COUNT(DISTINCT COALESCE(user_screen_name, username, '')) as unique_responders,
        SUM(COALESCE(favorite_count, like_count, 0)) as total_favorites,
        SUM(COALESCE(retweet_count, 0)) as total_retweets,
        AVG(COALESCE(favorite_count, like_count, 0)) as avg_favorites_per_reply,
        MIN(ingestion_date) as first_ingestion_date,
        MAX(ingestion_date) as last_ingestion_date,
        COUNT(DISTINCT ingestion_date) as days_with_data
      FROM `${var.project_id}.${var.bigquery_dataset}.replies`
      GROUP BY country, platform, candidate_id
      ORDER BY country, platform, candidate_id
    SQL
    use_legacy_sql = false
  }

  depends_on = [google_bigquery_table.replies]

  deletion_protection = false
}

# Output the table references
output "bigquery_dataset" {
  value       = google_bigquery_dataset.analytics.dataset_id
  description = "BigQuery dataset ID"
}

output "replies_table" {
  value       = "${var.project_id}.${var.bigquery_dataset}.${google_bigquery_table.replies.table_id}"
  description = "Full reference to the replies external table"
}

output "example_queries" {
  value = <<-EOT
    
    -- Query all replies for a candidate
    SELECT * FROM `${var.project_id}.${var.bigquery_dataset}.replies`
    WHERE candidate_id = 'hnd01monc'
    ORDER BY ingestion_date DESC
    LIMIT 100;
    
    -- Daily engagement summary
    SELECT * FROM `${var.project_id}.${var.bigquery_dataset}.daily_engagement`
    WHERE country = 'honduras'
    ORDER BY ingestion_date DESC;
    
    -- Filter by ingestion date (uses partition pruning - fast!)
    SELECT * FROM `${var.project_id}.${var.bigquery_dataset}.replies`
    WHERE ingestion_date = '2026-01-05';
    
  EOT
  description = "Example BigQuery queries"
}

