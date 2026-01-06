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
    autodetect    = false
    source_format = "PARQUET"
    source_uris   = ["gs://${var.gcs_bucket}/processed/replies/*"]

    # Explicit schema matching the unified schema from json_to_parquet.py
    schema = jsonencode([
      # Ingestion metadata
      { name = "ingestion_date", type = "DATE", mode = "NULLABLE" },
      { name = "ingestion_timestamp", type = "TIMESTAMP", mode = "NULLABLE" },
      { name = "source_file", type = "STRING", mode = "NULLABLE" },
      # Post context
      { name = "country", type = "STRING", mode = "NULLABLE" },
      { name = "platform", type = "STRING", mode = "NULLABLE" },
      { name = "candidate_id", type = "STRING", mode = "NULLABLE" },
      { name = "parent_post_id", type = "STRING", mode = "NULLABLE" },
      # Reply data
      { name = "tweet_id", type = "STRING", mode = "NULLABLE" },
      { name = "tweet_url", type = "STRING", mode = "NULLABLE" },
      { name = "created_at", type = "STRING", mode = "NULLABLE" },
      { name = "full_text", type = "STRING", mode = "NULLABLE" },
      { name = "lang", type = "STRING", mode = "NULLABLE" },
      # Author info
      { name = "user_id", type = "STRING", mode = "NULLABLE" },
      { name = "user_screen_name", type = "STRING", mode = "NULLABLE" },
      { name = "user_name", type = "STRING", mode = "NULLABLE" },
      { name = "user_followers_count", type = "INTEGER", mode = "NULLABLE" },
      { name = "user_friends_count", type = "INTEGER", mode = "NULLABLE" },
      { name = "user_verified", type = "BOOLEAN", mode = "NULLABLE" },
      # Engagement metrics
      { name = "reply_count", type = "INTEGER", mode = "NULLABLE" },
      { name = "retweet_count", type = "INTEGER", mode = "NULLABLE" },
      { name = "quote_count", type = "INTEGER", mode = "NULLABLE" },
      { name = "favorite_count", type = "INTEGER", mode = "NULLABLE" },
      # Tweet type flags
      { name = "is_reply", type = "BOOLEAN", mode = "NULLABLE" },
      { name = "is_retweet", type = "BOOLEAN", mode = "NULLABLE" },
      { name = "is_quote_status", type = "BOOLEAN", mode = "NULLABLE" },
      # Reply context
      { name = "in_reply_to_status_id_str", type = "STRING", mode = "NULLABLE" },
      { name = "in_reply_to_user_id_str", type = "STRING", mode = "NULLABLE" },
      { name = "in_reply_to_screen_name", type = "STRING", mode = "NULLABLE" },
      # Retweet context
      { name = "retweeted_status_id_str", type = "STRING", mode = "NULLABLE" },
      { name = "retweeted_status_screen_name", type = "STRING", mode = "NULLABLE" },
      # Media
      { name = "has_media", type = "BOOLEAN", mode = "NULLABLE" },
      { name = "media_count", type = "INTEGER", mode = "NULLABLE" },
      # Retry metadata
      { name = "is_retry", type = "BOOLEAN", mode = "NULLABLE" },
      { name = "retry_count", type = "INTEGER", mode = "NULLABLE" },
    ])

    # Hive partitioning: order matches directory structure (ingestion_date first, then platform)
    # Structure: processed/replies/ingestion_date={date}/platform={platform}/
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
        COUNT(DISTINCT user_screen_name) as unique_users,
        SUM(COALESCE(favorite_count, 0)) as total_favorites,
        SUM(COALESCE(retweet_count, 0)) as total_retweets,
        SUM(COALESCE(reply_count, 0)) as total_reply_count,
        AVG(COALESCE(favorite_count, 0)) as avg_favorites_per_reply,
        SUM(CASE WHEN is_retweet THEN 1 ELSE 0 END) as retweet_replies,
        SUM(CASE WHEN is_quote_status THEN 1 ELSE 0 END) as quote_replies,
        SUM(CASE WHEN has_media THEN 1 ELSE 0 END) as replies_with_media
      FROM `${var.project_id}.${var.bigquery_dataset}.replies`
      WHERE candidate_id IS NOT NULL AND candidate_id != ''
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
        COUNT(DISTINCT user_screen_name) as unique_responders,
        SUM(COALESCE(favorite_count, 0)) as total_favorites,
        SUM(COALESCE(retweet_count, 0)) as total_retweets,
        AVG(COALESCE(favorite_count, 0)) as avg_favorites_per_reply,
        MIN(ingestion_date) as first_ingestion_date,
        MAX(ingestion_date) as last_ingestion_date,
        COUNT(DISTINCT ingestion_date) as days_with_data
      FROM `${var.project_id}.${var.bigquery_dataset}.replies`
      WHERE candidate_id IS NOT NULL AND candidate_id != ''
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

