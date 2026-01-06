#!/usr/bin/env python3
"""
Transform JSON files from GCS to Parquet format for BigQuery analytics.

This script:
1. Reads JSON files from GCS (raw layer)
2. Flattens nested structures into tabular format
3. Adds ingestion metadata
4. Saves as Parquet partitioned by ingestion_date and platform
5. Optionally uploads to GCS processed layer

IMPORTANT: Only processes files in the correct structure:
    raw/{country}/{platform}/{candidate_id}/{post_id}.json

Files directly in raw/{country}/{platform}/ (without candidate_id subdirectory)
are automatically skipped.

Usage:
    # Process all JSONs and save Parquet locally
    poetry run python scripts/json_to_parquet.py --bucket trust-prd --country honduras --platform twitter

    # Process and upload to GCS processed layer
    poetry run python scripts/json_to_parquet.py --bucket trust-prd --country honduras --platform twitter --upload

    # Dry run (no writes)
    poetry run python scripts/json_to_parquet.py --bucket trust-prd --country honduras --platform twitter --dry-run

    # Filter by candidate
    poetry run python scripts/json_to_parquet.py --bucket trust-prd --country honduras --platform twitter --candidate-id hnd01monc
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

# Check for required dependencies
try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:
    print("ERROR: pyarrow is required. Install with: poetry add pyarrow")
    sys.exit(1)

try:
    from google.cloud import storage
except ImportError:
    print("ERROR: google-cloud-storage is required. Install with: poetry add google-cloud-storage")
    sys.exit(1)


# Schema for Twitter replies (Information Tracer format)
TWITTER_SCHEMA = pa.schema(
    [
        # Ingestion metadata
        ("ingestion_date", pa.date32()),
        ("ingestion_timestamp", pa.timestamp("us", tz="UTC")),
        ("source_file", pa.string()),
        # Post context (from file path)
        ("country", pa.string()),
        ("platform", pa.string()),
        ("candidate_id", pa.string()),
        ("parent_post_id", pa.string()),
        # Reply data
        ("tweet_id", pa.string()),
        ("tweet_url", pa.string()),
        ("created_at", pa.string()),  # Keep as string, parse later if needed
        ("full_text", pa.string()),
        ("lang", pa.string()),
        # Author info
        ("user_id", pa.string()),
        ("user_screen_name", pa.string()),
        ("user_name", pa.string()),
        ("user_followers_count", pa.int64()),
        ("user_friends_count", pa.int64()),
        ("user_verified", pa.bool_()),
        # Engagement metrics
        ("reply_count", pa.int64()),
        ("retweet_count", pa.int64()),
        ("quote_count", pa.int64()),
        ("favorite_count", pa.int64()),
        # Tweet type flags
        ("is_reply", pa.bool_()),
        ("is_retweet", pa.bool_()),
        ("is_quote_status", pa.bool_()),
        # Reply context
        ("in_reply_to_status_id_str", pa.string()),
        ("in_reply_to_user_id_str", pa.string()),
        ("in_reply_to_screen_name", pa.string()),
        # Retweet context
        ("retweeted_status_id_str", pa.string()),
        ("retweeted_status_screen_name", pa.string()),
        # Media
        ("has_media", pa.bool_()),
        ("media_count", pa.int64()),
        # Retry metadata (if present)
        ("is_retry", pa.bool_()),
        ("retry_count", pa.int64()),
    ]
)

INSTAGRAM_SCHEMA = pa.schema(
    [
        # Ingestion metadata
        ("ingestion_date", pa.date32()),
        ("ingestion_timestamp", pa.timestamp("us", tz="UTC")),
        ("source_file", pa.string()),
        # Post context
        ("country", pa.string()),
        ("platform", pa.string()),
        ("candidate_id", pa.string()),
        ("parent_post_id", pa.string()),
        # Comment data (using Twitter field names for consistency)
        ("tweet_id", pa.string()),  # Maps to comment_id for Instagram
        ("tweet_url", pa.string()),  # Empty for Instagram
        ("created_at", pa.string()),
        ("full_text", pa.string()),  # Maps to text for Instagram
        ("lang", pa.string()),  # Empty for Instagram
        # Author info (using Twitter field names for consistency)
        ("user_id", pa.string()),
        ("user_screen_name", pa.string()),  # Maps to username for Instagram
        ("user_name", pa.string()),  # Maps to full_name for Instagram
        ("user_followers_count", pa.int64()),  # Empty for Instagram
        ("user_friends_count", pa.int64()),  # Empty for Instagram
        ("user_verified", pa.bool_()),  # Maps to is_verified for Instagram
        # Engagement metrics (using Twitter field names)
        ("reply_count", pa.int64()),
        ("retweet_count", pa.int64()),  # Empty for Instagram
        ("quote_count", pa.int64()),  # Empty for Instagram
        ("favorite_count", pa.int64()),  # Maps to like_count for Instagram
        # Tweet type flags
        ("is_reply", pa.bool_()),  # Empty for Instagram
        ("is_retweet", pa.bool_()),  # Empty for Instagram
        ("is_quote_status", pa.bool_()),  # Empty for Instagram
        # Reply context (empty for Instagram)
        ("in_reply_to_status_id_str", pa.string()),
        ("in_reply_to_user_id_str", pa.string()),
        ("in_reply_to_screen_name", pa.string()),
        # Retweet context (empty for Instagram)
        ("retweeted_status_id_str", pa.string()),
        ("retweeted_status_screen_name", pa.string()),
        # Media
        ("has_media", pa.bool_()),  # Empty for Instagram
        ("media_count", pa.int64()),  # Empty for Instagram
        # Retry metadata
        ("is_retry", pa.bool_()),
        ("retry_count", pa.int64()),
    ]
)


def parse_gcs_path(blob_name: str) -> dict[str, str]:
    """
    Parse GCS blob path to extract metadata.

    Expected format: raw/{country}/{platform}/{candidate_id}/{post_id}.json

    Only processes files with candidate_id as a subdirectory.
    Files directly in raw/{country}/{platform}/ are ignored.
    """
    parts = blob_name.replace(".json", "").split("/")

    # Handle both raw/ prefix and direct paths
    if parts[0] == "raw":
        parts = parts[1:]

    if len(parts) >= 4:
        # Correct format: country, platform, candidate_id, post_id
        return {
            "country": parts[0],
            "platform": parts[1],
            "candidate_id": parts[2],
            "parent_post_id": parts[3],
        }
    else:
        # Invalid structure - should not happen if filtering is correct
        return {
            "country": parts[0] if len(parts) > 0 else "",
            "platform": parts[1] if len(parts) > 1 else "",
            "candidate_id": "",
            "parent_post_id": parts[-1] if parts else "",
        }


def is_retweet(item: dict[str, Any]) -> bool:
    """Check if a tweet is a retweet."""
    if item.get("retweeted_status_id_str") or item.get("retweeted_status_screen_name"):
        return True
    if str(item.get("full_text", "")).startswith("RT @"):
        return True
    if item.get("retweeted") is True and item.get("is_quote_status") is False:
        return True
    return False


def safe_int(value: Any, default: int = 0) -> int:
    """Safely convert to int."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def safe_str(value: Any, default: str = "") -> str:
    """Safely convert to string."""
    if value is None:
        return default
    return str(value)


def safe_bool(value: Any, default: bool = False) -> bool:
    """Safely convert to bool."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return bool(value)


def flatten_twitter_record(
    item: dict[str, Any],
    context: dict[str, str],
    ingestion_ts: datetime,
    source_file: str,
    retry_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Flatten a Twitter reply record into a flat dictionary."""
    user = item.get("user", {}) or {}
    media = item.get("entities", {}).get("media", []) or []

    return {
        # Ingestion metadata
        "ingestion_date": ingestion_ts.date(),
        "ingestion_timestamp": ingestion_ts,
        "source_file": source_file,
        # Post context
        "country": context.get("country", ""),
        "platform": context.get("platform", "twitter"),
        "candidate_id": context.get("candidate_id", ""),
        "parent_post_id": context.get("parent_post_id", ""),
        # Reply data
        "tweet_id": safe_str(item.get("id_str") or item.get("tweet_id")),
        "tweet_url": safe_str(item.get("tweet_url")),
        "created_at": safe_str(item.get("created_at")),
        "full_text": safe_str(item.get("full_text") or item.get("text")),
        "lang": safe_str(item.get("lang")),
        # Author info
        "user_id": safe_str(user.get("id_str") or item.get("user_id_str")),
        "user_screen_name": safe_str(user.get("screen_name") or item.get("user_screen_name")),
        "user_name": safe_str(user.get("name") or item.get("user_name")),
        "user_followers_count": safe_int(user.get("followers_count")),
        "user_friends_count": safe_int(user.get("friends_count")),
        "user_verified": safe_bool(user.get("verified")),
        # Engagement metrics
        "reply_count": safe_int(item.get("reply_count")),
        "retweet_count": safe_int(item.get("retweet_count")),
        "quote_count": safe_int(item.get("quote_count")),
        "favorite_count": safe_int(item.get("favorite_count")),
        # Tweet type flags
        "is_reply": bool(item.get("in_reply_to_status_id_str")),
        "is_retweet": is_retweet(item),
        "is_quote_status": safe_bool(item.get("is_quote_status")),
        # Reply context
        "in_reply_to_status_id_str": safe_str(item.get("in_reply_to_status_id_str")),
        "in_reply_to_user_id_str": safe_str(item.get("in_reply_to_user_id_str")),
        "in_reply_to_screen_name": safe_str(item.get("in_reply_to_screen_name")),
        # Retweet context
        "retweeted_status_id_str": safe_str(item.get("retweeted_status_id_str")),
        "retweeted_status_screen_name": safe_str(item.get("retweeted_status_screen_name")),
        # Media
        "has_media": len(media) > 0,
        "media_count": len(media),
        # Retry metadata
        "is_retry": retry_metadata.get("is_retry", False) if retry_metadata else False,
        "retry_count": retry_metadata.get("retry_count", 0) if retry_metadata else 0,
    }


def flatten_instagram_record(
    item: dict[str, Any],
    context: dict[str, str],
    ingestion_ts: datetime,
    source_file: str,
    retry_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Flatten an Instagram comment record into a flat dictionary.

    Uses the same field names as Twitter for schema consistency.
    """
    user = item.get("user", {}) or item.get("owner", {}) or {}

    return {
        # Ingestion metadata
        "ingestion_date": ingestion_ts.date(),
        "ingestion_timestamp": ingestion_ts,
        "source_file": source_file,
        # Post context
        "country": context.get("country", ""),
        "platform": context.get("platform", "instagram"),
        "candidate_id": context.get("candidate_id", ""),
        "parent_post_id": context.get("parent_post_id", ""),
        # Comment data (using Twitter field names for consistency)
        "tweet_id": safe_str(item.get("id") or item.get("pk")),  # Maps from comment_id
        "tweet_url": "",  # Instagram doesn't have tweet URLs
        "created_at": safe_str(item.get("created_at") or item.get("taken_at")),
        "full_text": safe_str(item.get("text")),  # Maps from text
        "lang": "",  # Instagram doesn't provide language
        # Author info (using Twitter field names for consistency)
        "user_id": safe_str(user.get("id") or user.get("pk")),
        "user_screen_name": safe_str(user.get("username")),  # Maps from username
        "user_name": safe_str(user.get("full_name")),  # Maps from full_name
        "user_followers_count": 0,  # Instagram doesn't provide this in comments
        "user_friends_count": 0,  # Instagram doesn't provide this
        "user_verified": safe_bool(user.get("is_verified")),
        # Engagement metrics (using Twitter field names)
        "reply_count": safe_int(item.get("child_comment_count")),
        "retweet_count": 0,  # Instagram doesn't have retweets
        "quote_count": 0,  # Instagram doesn't have quotes
        "favorite_count": safe_int(
            item.get("like_count") or item.get("comment_like_count")
        ),  # Maps from like_count
        # Tweet type flags
        "is_reply": False,  # Instagram comments are always replies
        "is_retweet": False,  # Instagram doesn't have retweets
        "is_quote_status": False,  # Instagram doesn't have quotes
        # Reply context (empty for Instagram)
        "in_reply_to_status_id_str": "",
        "in_reply_to_user_id_str": "",
        "in_reply_to_screen_name": "",
        # Retweet context (empty for Instagram)
        "retweeted_status_id_str": "",
        "retweeted_status_screen_name": "",
        # Media
        "has_media": False,  # Could be enhanced to check for media in comments
        "media_count": 0,
        # Retry metadata
        "is_retry": retry_metadata.get("is_retry", False) if retry_metadata else False,
        "retry_count": retry_metadata.get("retry_count", 0) if retry_metadata else 0,
    }


def process_json_file(
    data: dict[str, Any] | list[Any],
    blob_name: str,
    ingestion_ts: datetime,
) -> tuple[list[dict[str, Any]], str]:
    """
    Process a JSON file and return flattened records.

    Returns:
        Tuple of (records, platform)
    """
    context = parse_gcs_path(blob_name)
    platform = context.get("platform", "unknown")

    # Extract retry metadata if present
    retry_metadata = None
    if isinstance(data, dict) and "_metadata" in data:
        retry_metadata = data.get("_metadata")
        # Remove metadata from data for processing
        data = {k: v for k, v in data.items() if k != "_metadata"}

    # Handle different data structures
    records_list: list[dict[str, Any]] = []

    if isinstance(data, list):
        records_list = data
    elif isinstance(data, dict):
        # Some responses wrap data in a key
        if "data" in data:
            records_list = data["data"] if isinstance(data["data"], list) else [data["data"]]
        else:
            records_list = [data]

    # Flatten records based on platform
    flattened = []
    for item in records_list:
        if not isinstance(item, dict):
            continue

        if platform == "twitter":
            flattened.append(
                flatten_twitter_record(item, context, ingestion_ts, blob_name, retry_metadata)
            )
        elif platform == "instagram":
            flattened.append(
                flatten_instagram_record(item, context, ingestion_ts, blob_name, retry_metadata)
            )
        else:
            # Generic fallback - use Twitter schema
            flattened.append(
                flatten_twitter_record(item, context, ingestion_ts, blob_name, retry_metadata)
            )

    return flattened, platform


def read_json_from_gcs(
    bucket_name: str,
    prefix: str,
    candidate_filter: str | None = None,
) -> list[tuple[str, dict[str, Any] | list[Any], datetime]]:
    """
    Read all JSON files from GCS.

    Returns:
        List of (blob_name, data, last_modified)
    """
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    results = []
    blobs = bucket.list_blobs(prefix=prefix)

    for blob in blobs:
        if not blob.name.lower().endswith(".json"):
            continue

        # Only process files in the correct structure: raw/{country}/{platform}/{candidate_id}/{post_id}.json
        # Skip files directly in raw/{country}/{platform}/ (without candidate_id subdirectory)
        parts = blob.name.split("/")

        # Remove 'raw' prefix if present for counting
        path_parts = parts[1:] if parts[0] == "raw" else parts

        # Must have at least 4 parts: country, platform, candidate_id, post_id
        if len(path_parts) < 4:
            print(
                f"  SKIP: File not in correct structure (missing candidate_id directory): {blob.name}"
            )
            continue

        # Apply candidate filter if specified
        if candidate_filter:
            # Check if candidate_id is in the path (should be at index 2 after removing 'raw')
            if candidate_filter not in parts:
                continue

        try:
            raw = blob.download_as_text(encoding="utf-8")
            data = json.loads(raw)

            # Use blob's last modified time as ingestion timestamp
            ingestion_ts = blob.updated or datetime.now(timezone.utc)
            if ingestion_ts.tzinfo is None:
                ingestion_ts = ingestion_ts.replace(tzinfo=timezone.utc)

            results.append((blob.name, data, ingestion_ts))
        except json.JSONDecodeError as e:
            print(f"  WARNING: Invalid JSON in {blob.name}: {e}")
            continue
        except Exception as e:
            print(f"  ERROR reading {blob.name}: {e}")
            continue

    return results


def records_to_parquet(
    records: list[dict[str, Any]],
    schema: pa.Schema,
    output_path: str,
) -> int:
    """
    Convert records to Parquet file.

    Returns:
        Number of records written
    """
    if not records:
        return 0

    # Convert to PyArrow table
    table = pa.Table.from_pylist(records, schema=schema)

    # Write to Parquet
    pq.write_table(table, output_path, compression="snappy")

    return len(records)


def upload_to_gcs(
    local_path: str,
    bucket_name: str,
    blob_path: str,
) -> str:
    """Upload file to GCS and return URI."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_path)

    blob.upload_from_filename(local_path)

    return f"gs://{bucket_name}/{blob_path}"


def main():
    parser = argparse.ArgumentParser(description="Transform JSON files from GCS to Parquet format")
    parser.add_argument(
        "--bucket",
        required=True,
        help="GCS bucket name",
    )
    parser.add_argument(
        "--prefix",
        default=None,
        help="GCS prefix to read from (e.g., raw/honduras/twitter). If not provided, uses --country and --platform.",
    )
    parser.add_argument(
        "--country",
        default=None,
        help="Country name (used with --platform to build prefix)",
    )
    parser.add_argument(
        "--platform",
        default=None,
        help="Platform name: twitter, instagram, youtube, etc.",
    )
    parser.add_argument(
        "--candidate-id",
        default=None,
        help="Filter by candidate ID",
    )
    parser.add_argument(
        "--output-dir",
        default="./data/processed",
        help="Local output directory for Parquet files",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload Parquet files to GCS processed/ layer",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't write any files, just show what would be done",
    )

    args = parser.parse_args()

    # Build prefix
    prefix = args.prefix
    if not prefix and args.country and args.platform:
        prefix = f"raw/{args.country}/{args.platform}"
    elif not prefix and args.country:
        prefix = f"raw/{args.country}"

    if not prefix:
        print("ERROR: Must provide --prefix or --country")
        sys.exit(1)

    print("=== JSON to Parquet Transformation ===")
    print(f"Bucket: {args.bucket}")
    print(f"Prefix: {prefix}")
    if args.candidate_id:
        print(f"Candidate filter: {args.candidate_id}")
    print(f"Output dir: {args.output_dir}")
    print(f"Upload to GCS: {args.upload}")
    print(f"Dry run: {args.dry_run}")
    print()

    # Read JSON files
    print("Reading JSON files from GCS...")
    json_files = read_json_from_gcs(args.bucket, prefix, args.candidate_id)
    print(f"Found {len(json_files)} JSON files")

    if not json_files:
        print("No files to process")
        return

    # Group records by ingestion date and platform
    # Partition order: ingestion_date first, then platform (matches BigQuery expectations)
    records_by_partition: dict[tuple[str, str], list[dict[str, Any]]] = {}

    print("Processing JSON files...")
    for blob_name, data, ingestion_ts in json_files:
        flattened, platform = process_json_file(data, blob_name, ingestion_ts)

        if not flattened:
            continue

        # Partition key: (ingestion_date, platform) - ingestion_date first for BigQuery
        date_str = ingestion_ts.strftime("%Y-%m-%d")
        key = (date_str, platform)

        if key not in records_by_partition:
            records_by_partition[key] = []
        records_by_partition[key].extend(flattened)

    # Summary
    total_records = sum(len(r) for r in records_by_partition.values())
    print(f"\nTotal records: {total_records}")
    print(f"Partitions: {len(records_by_partition)}")

    for (date_str, platform), records in sorted(records_by_partition.items()):
        print(f"  ingestion_date={date_str}/platform={platform}: {len(records)} records")

    if args.dry_run:
        print("\n[DRY RUN] No files written")
        return

    # Write Parquet files
    print("\nWriting Parquet files...")
    output_dir = Path(args.output_dir)
    written_files = []

    for (date_str, platform), records in records_by_partition.items():
        # Use unified schema for all platforms (Instagram now uses same field names as Twitter)
        schema = TWITTER_SCHEMA

        # Create partition directory: ingestion_date first, then platform
        partition_dir = (
            output_dir / "replies" / f"ingestion_date={date_str}" / f"platform={platform}"
        )
        partition_dir.mkdir(parents=True, exist_ok=True)

        # Write Parquet file
        parquet_path = partition_dir / "data.parquet"
        count = records_to_parquet(records, schema, str(parquet_path))

        print(f"  Wrote {count} records to {parquet_path}")
        written_files.append((str(parquet_path), date_str, platform))

    # Upload to GCS if requested
    if args.upload:
        print("\nUploading to GCS...")
        for local_path, date_str, platform in written_files:
            blob_path = (
                f"processed/replies/ingestion_date={date_str}/platform={platform}/data.parquet"
            )
            uri = upload_to_gcs(local_path, args.bucket, blob_path)
            print(f"  Uploaded: {uri}")

    print("\nDone!")

    # Print BigQuery external table hint
    print("\n" + "=" * 60)
    print("To create a BigQuery External Table, run:")
    print("=" * 60)
    print(f"""
CREATE EXTERNAL TABLE `your_project.your_dataset.replies`
WITH PARTITION COLUMNS (
  ingestion_date DATE,
  platform STRING
)
OPTIONS (
  format = 'PARQUET',
  uris = ['gs://{args.bucket}/processed/replies/*'],
  hive_partition_uri_prefix = 'gs://{args.bucket}/processed/replies/'
);
""")


if __name__ == "__main__":
    main()
