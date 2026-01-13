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
    source_uris   = ["gs://${var.gcs_bucket}/marts/replies/*"]

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
    # Structure: marts/replies/ingestion_date={date}/platform={platform}/
    hive_partitioning_options {
      mode                     = "AUTO"
      source_uri_prefix        = "gs://${var.gcs_bucket}/marts/replies/"
      require_partition_filter = false
    }
  }

  labels = {
    data_source = "information_tracer"
    layer       = "processed"
  }

  deletion_protection = false
}

# External table for consolidated posts
resource "google_bigquery_table" "posts" {
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  project    = var.project_id
  table_id   = "posts"

  description = "External table for consolidated posts from Firestore with real replies count from Parquet"

  external_data_configuration {
    autodetect    = false
    source_format = "PARQUET"
    source_uris   = ["gs://${var.gcs_bucket}/marts/posts/*"]

    # Explicit schema matching the posts schema from create_posts_consolidated.py
    schema = jsonencode([
      # Post identification
      { name = "post_id", type = "STRING", mode = "NULLABLE" },
      { name = "country", type = "STRING", mode = "NULLABLE" },
      { name = "platform", type = "STRING", mode = "NULLABLE" },
      { name = "candidate_id", type = "STRING", mode = "NULLABLE" },
      # Post metadata
      { name = "created_at", type = "TIMESTAMP", mode = "NULLABLE" },
      { name = "replies_count", type = "INTEGER", mode = "NULLABLE" },
      { name = "max_replies", type = "INTEGER", mode = "NULLABLE" },
      { name = "status", type = "STRING", mode = "NULLABLE" },
      { name = "updated_at", type = "TIMESTAMP", mode = "NULLABLE" },
      # Real replies count (from Parquet)
      { name = "real_replies_count", type = "INTEGER", mode = "NULLABLE" },
      # Ingestion metadata
      { name = "ingestion_date", type = "DATE", mode = "NULLABLE" },
      { name = "ingestion_timestamp", type = "TIMESTAMP", mode = "NULLABLE" },
    ])

    # Hive partitioning: order matches directory structure (platform first, then ingestion_date)
    # Structure: marts/posts/platform={platform}/ingestion_date={date}/
    hive_partitioning_options {
      mode                     = "AUTO"
      source_uri_prefix        = "gs://${var.gcs_bucket}/marts/posts/"
      require_partition_filter = false
    }
  }

  labels = {
    data_source = "firestore"
    layer       = "marts"
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

output "keywordpost_table" {
  value       = "${var.project_id}.${var.bigquery_dataset}.${google_bigquery_table.keywordpost.table_id}"
  description = "Full reference to the keywordpost external table"
}

output "keywordpost_replies_table" {
  value       = "${var.project_id}.${var.bigquery_dataset}.${google_bigquery_table.keywordpost_replies.table_id}"
  description = "Full reference to the keywordpost_replies external table"
}

output "posts_table" {
  value       = "${var.project_id}.${var.bigquery_dataset}.${google_bigquery_table.posts.table_id}"
  description = "Full reference to the posts consolidated external table"
}

output "ownpost_table" {
  value       = "${var.project_id}.${var.bigquery_dataset}.${google_bigquery_table.ownpost.table_id}"
  description = "Full reference to the ownpost external table"
}

output "keywordpost_filtered_table" {
  value       = "${var.project_id}.${var.bigquery_dataset}.${google_bigquery_table.keywordpost_filtered.table_id}"
  description = "Full reference to the keywordpost_filtered external table"
}

# External table for YouTube keyword posts (videos)
resource "google_bigquery_table" "keywordpost" {
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  project    = var.project_id
  table_id   = "keywordpost"

  description = "External table for YouTube keyword posts (videos) stored as Parquet in GCS"

  external_data_configuration {
    autodetect    = false
    source_format = "PARQUET"
    # Match keyword post files (videos) - exclude replies files by using specific pattern
    # Pattern matches: yt_keywordpost_*.parquet but not *replies*.parquet
    source_uris   = [
      "gs://${var.gcs_bucket}/stg/keywordpost/youtube/yt_keywordpost_*.parquet"
    ]

    # Schema matching the YouTube keyword post Parquet files
    schema = jsonencode([
      { name = "id", type = "STRING", mode = "NULLABLE" },
      { name = "url", type = "STRING", mode = "NULLABLE" },
      { name = "channel_id", type = "STRING", mode = "NULLABLE" },
      { name = "title", type = "STRING", mode = "NULLABLE" },
      { name = "description", type = "STRING", mode = "NULLABLE" },
      { name = "channel_title", type = "STRING", mode = "NULLABLE" },
      { name = "published_at", type = "TIMESTAMP", mode = "NULLABLE" },
      { name = "thumbnail_url", type = "STRING", mode = "NULLABLE" },
      { name = "tags", type = "STRING", mode = "REPEATED" },
      { name = "duration", type = "STRING", mode = "NULLABLE" },
      { name = "view_count", type = "INTEGER", mode = "NULLABLE" },
      { name = "like_count", type = "INTEGER", mode = "NULLABLE" },
      { name = "comment_count", type = "INTEGER", mode = "NULLABLE" },
      { name = "language", type = "STRING", mode = "NULLABLE" },
      { name = "posttype", type = "STRING", mode = "NULLABLE" },
      { name = "country", type = "STRING", mode = "NULLABLE" },
      { name = "candidate_id", type = "STRING", mode = "NULLABLE" },
    ])
  }

  labels = {
    data_source = "information_tracer"
    layer       = "processed"
  }

  deletion_protection = false
}

# External table for YouTube keyword post replies (comments)
resource "google_bigquery_table" "keywordpost_replies" {
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  project    = var.project_id
  table_id   = "keywordpost_replies"

  description = "External table for YouTube keyword post replies (comments) stored as Parquet in GCS"

  external_data_configuration {
    autodetect    = false
    source_format = "PARQUET"
    source_uris   = ["gs://${var.gcs_bucket}/stg/keywordpost/*/*replies*.parquet"]

    # Schema matching the YouTube keyword post replies Parquet files
    schema = jsonencode([
      { name = "video_id", type = "STRING", mode = "NULLABLE" },
      { name = "video_title", type = "STRING", mode = "NULLABLE" },
      { name = "video_description", type = "STRING", mode = "NULLABLE" },
      { name = "video_url", type = "STRING", mode = "NULLABLE" },
      { name = "channel_id", type = "STRING", mode = "NULLABLE" },
      { name = "channel_title", type = "STRING", mode = "NULLABLE" },
      { name = "video_published_at", type = "TIMESTAMP", mode = "NULLABLE" },
      { name = "thumbnail_url", type = "STRING", mode = "NULLABLE" },
      { name = "comment_id", type = "STRING", mode = "NULLABLE" },
      { name = "author", type = "STRING", mode = "NULLABLE" },
      { name = "text", type = "STRING", mode = "NULLABLE" },
      { name = "like_count", type = "INTEGER", mode = "NULLABLE" },
      { name = "published_at", type = "TIMESTAMP", mode = "NULLABLE" },
      { name = "reply_count", type = "INTEGER", mode = "NULLABLE" },
      { name = "posttype", type = "STRING", mode = "NULLABLE" },
      { name = "country", type = "STRING", mode = "NULLABLE" },
      { name = "candidate_id", type = "STRING", mode = "NULLABLE" },
    ])
  }

  labels = {
    data_source = "information_tracer"
    layer       = "processed"
  }

  deletion_protection = false
}

# External table for ownposts (posts propios de candidatos)
resource "google_bigquery_table" "ownpost" {
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  project    = var.project_id
  table_id   = "ownpost"

  description = "External table for ownposts (posts propios de candidatos) stored as Parquet in GCS"

  external_data_configuration {
    autodetect    = true
    source_format = "PARQUET"
    source_uris   = ["gs://${var.gcs_bucket}/stg/ownpost/*"]

    # Using autodetect=true to automatically detect schema from Parquet files
    # The Parquet files contain Twitter/Instagram post data with fields like:
    # id_str, reply_count, favorite_count, full_text, created_at, etc.
    # Plus metadata fields: posttype, country, candidate_id, error_*

    # Note: Files are organized as stg/ownpost/{platform}/*.parquet
    # (not in Hive partition format: platform={platform}/)
    # So we don't use hive_partitioning_options
    # The platform field is available in the data itself for filtering
  }

  labels = {
    data_source = "information_tracer"
    layer       = "staging"
  }

  deletion_protection = false
}

# External table for filtered YouTube keyword posts (videos)
resource "google_bigquery_table" "keywordpost_filtered" {
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  project    = var.project_id
  table_id   = "keywordpost_filtered"

  description = "External table for filtered YouTube keyword posts (videos) stored as Parquet in GCS"

  external_data_configuration {
    autodetect    = true
    source_format = "PARQUET"
    source_uris   = ["gs://${var.gcs_bucket}/stg/keywordpost_filtered/youtube/*"]

    # Using autodetect=true to automatically detect schema from Parquet files
    # The Parquet files contain YouTube video data with fields similar to keywordpost
    # but filtered/processed
  }

  labels = {
    data_source = "information_tracer"
    layer       = "staging"
  }

  deletion_protection = false
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
    
    -- Query keyword posts (videos)
    SELECT * FROM `${var.project_id}.${var.bigquery_dataset}.keywordpost`
    WHERE country = 'honduras'
    ORDER BY published_at DESC
    LIMIT 100;
    
    -- Query keyword post replies (comments)
    SELECT * FROM `${var.project_id}.${var.bigquery_dataset}.keywordpost_replies`
    WHERE country = 'honduras'
    ORDER BY published_at DESC
    LIMIT 100;
    
    -- Query filtered keyword posts (videos)
    SELECT * FROM `${var.project_id}.${var.bigquery_dataset}.keywordpost_filtered`
    WHERE country = 'honduras'
    ORDER BY published_at DESC
    LIMIT 100;
    
    -- Query ownposts (posts propios de candidatos)
    SELECT * FROM `${var.project_id}.${var.bigquery_dataset}.ownpost`
    WHERE platform = 'twitter'
    ORDER BY created_at DESC
    LIMIT 100;
    
    -- Query ownposts by country and platform
    SELECT 
      country,
      platform,
      candidate_id,
      COUNT(*) as total_posts,
      SUM(replies_count) as total_replies,
      AVG(replies_count) as avg_replies_per_post
    FROM `${var.project_id}.${var.bigquery_dataset}.ownpost`
    WHERE country = 'honduras'
    GROUP BY country, platform, candidate_id
    ORDER BY country, platform, candidate_id;
    
    -- Query consolidated posts with real replies count
    SELECT 
      post_id,
      country,
      platform,
      candidate_id,
      max_replies,
      real_replies_count,
      status,
      created_at
    FROM `${var.project_id}.${var.bigquery_dataset}.posts`
    WHERE country = 'honduras'
    ORDER BY ingestion_date DESC
    LIMIT 100;
    
    -- Compare max_replies vs real_replies_count
    SELECT 
      country,
      platform,
      candidate_id,
      COUNT(*) as total_posts,
      SUM(max_replies) as total_max_replies,
      SUM(real_replies_count) as total_real_replies,
      AVG(real_replies_count) as avg_real_replies_per_post
    FROM `${var.project_id}.${var.bigquery_dataset}.posts`
    GROUP BY country, platform, candidate_id
    ORDER BY country, platform, candidate_id;
    
  EOT
  description = "Example BigQuery queries"
}

