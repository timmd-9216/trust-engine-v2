#!/usr/bin/env python3
"""
Create consolidated posts table from Firestore and count real replies from Parquet.

This script:
1. Reads posts from Firestore (with max_posts_replies field)
2. Counts real replies scrapped from Parquet files (using parent_post_id)
3. Saves as Parquet partitioned by ingestion_date and platform
4. Optionally uploads to GCS marts layer

Usage:
    # Process all posts and save Parquet locally
    poetry run python scripts/create_posts_consolidated.py --bucket trust-prd

    # Process and upload to GCS marts layer
    poetry run python scripts/create_posts_consolidated.py --bucket trust-prd --upload

    # Dry run (no writes)
    poetry run python scripts/create_posts_consolidated.py --bucket trust-prd --dry-run
"""

import argparse
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
    from google.cloud import firestore, storage
except ImportError:
    print("ERROR: google-cloud-storage and google-cloud-firestore are required.")
    print("Install with: poetry add google-cloud-storage google-cloud-firestore")
    sys.exit(1)


# Schema for consolidated posts
POSTS_SCHEMA = pa.schema(
    [
        # Post identification
        ("post_id", pa.string()),
        ("country", pa.string()),
        ("platform", pa.string()),
        ("candidate_id", pa.string()),
        # Post metadata
        ("created_at", pa.timestamp("us", tz="UTC")),
        ("replies_count", pa.int64()),  # From Firestore
        ("max_posts_replies", pa.int64()),  # From Firestore
        ("status", pa.string()),
        ("updated_at", pa.timestamp("us", tz="UTC")),
        # Real replies count (from Parquet)
        ("real_replies_count", pa.int64()),
        # Ingestion metadata
        ("ingestion_date", pa.date32()),
        ("ingestion_timestamp", pa.timestamp("us", tz="UTC")),
    ]
)


def get_firestore_client(
    project_id: str | None = None, database: str = "socialnetworks"
) -> firestore.Client:
    """Initialize and return Firestore client."""
    if project_id:
        return firestore.Client(project=project_id, database=database)
    return firestore.Client(database=database)


def read_posts_from_firestore(
    project_id: str | None = None,
    database: str = "socialnetworks",
    collection: str = "posts",
) -> list[dict[str, Any]]:
    """
    Read all posts from Firestore.

    Returns:
        List of post documents with all fields from Firestore.
    """
    client = get_firestore_client(project_id, database)

    posts = []
    for doc in client.collection(collection).stream():
        doc_data = doc.to_dict()
        doc_data["_doc_id"] = doc.id
        posts.append(doc_data)

    return posts


def count_all_replies_from_parquet(
    bucket: storage.Bucket,
) -> dict[tuple[str, str], int]:
    """
    Count replies for all posts from Parquet files in one pass.

    Args:
        bucket: GCS bucket object

    Returns:
        Dictionary mapping (post_id, platform) -> count of replies
    """
    if not pa or not pq:
        return {}

    # Dictionary to store counts: (post_id, platform) -> count
    reply_counts: dict[tuple[str, str], int] = {}

    # Search in all date partitions
    # Path structure: marts/replies/ingestion_date={date}/platform={platform}/data.parquet
    blobs = bucket.list_blobs(prefix="marts/replies/")

    processed_files = set()  # Avoid counting same file multiple times

    for blob in blobs:
        if not blob.name.endswith("data.parquet"):
            continue

        # Extract platform from path
        # Path format: marts/replies/ingestion_date={date}/platform={platform}/data.parquet
        if "/platform=" not in blob.name:
            continue

        platform = ""
        try:
            # Extract platform from path
            parts = blob.name.split("/platform=")
            if len(parts) > 1:
                platform = parts[1].split("/")[0]
        except Exception:
            continue

        if not platform:
            continue

        # Skip if already processed (same file path)
        if blob.name in processed_files:
            continue
        processed_files.add(blob.name)

        try:
            # Download and read Parquet file
            parquet_data = blob.download_as_bytes()
            import io

            parquet_file = io.BytesIO(parquet_data)
            table = pq.read_table(parquet_file)

            # Check if parent_post_id column exists
            if "parent_post_id" not in table.column_names:
                continue

            # Count replies by parent_post_id
            try:
                import pandas as pd  # noqa: F401

                df = table.to_pandas()
                # Group by parent_post_id and count
                counts = df["parent_post_id"].value_counts()
                for parent_post_id, count in counts.items():
                    if parent_post_id:  # Skip empty/null values
                        key = (str(parent_post_id), platform)
                        reply_counts[key] = reply_counts.get(key, 0) + int(count)
            except ImportError:
                # Fallback: iterate through records
                records = table.to_pylist()
                for record in records:
                    parent_post_id = record.get("parent_post_id")
                    if parent_post_id:
                        key = (str(parent_post_id), platform)
                        reply_counts[key] = reply_counts.get(key, 0) + 1

        except Exception as e:
            # Skip files that can't be read
            print(f"  WARNING: Could not read {blob.name}: {e}")
            continue

    return reply_counts


def count_replies_from_parquet(
    bucket: storage.Bucket,
    post_id: str,
    platform: str,
    reply_counts_cache: dict[tuple[str, str], int] | None = None,
) -> int:
    """
    Count replies for a specific post from Parquet files.

    Args:
        bucket: GCS bucket object
        post_id: The parent_post_id to search for
        platform: Platform name (twitter, instagram, etc.)
        reply_counts_cache: Optional pre-computed cache of reply counts

    Returns:
        Count of replies found in Parquet files
    """
    if reply_counts_cache is not None:
        return reply_counts_cache.get((post_id, platform), 0)

    # If no cache provided, use the old method (less efficient)
    # This is kept for backward compatibility
    if not pa or not pq:
        return 0

    count = 0

    # Search in all date partitions
    blobs = bucket.list_blobs(prefix="marts/replies/")

    processed_files = set()

    for blob in blobs:
        if not blob.name.endswith("data.parquet"):
            continue

        if f"/platform={platform}/" not in blob.name:
            continue

        if blob.name in processed_files:
            continue
        processed_files.add(blob.name)

        try:
            parquet_data = blob.download_as_bytes()
            import io

            parquet_file = io.BytesIO(parquet_data)
            table = pq.read_table(parquet_file)

            if "parent_post_id" not in table.column_names:
                continue

            try:
                import pandas as pd  # noqa: F401

                df = table.to_pandas()
                count += len(df[df["parent_post_id"] == post_id])
            except ImportError:
                records = table.to_pylist()
                for record in records:
                    if record.get("parent_post_id") == post_id:
                        count += 1

        except Exception as e:
            print(f"  WARNING: Could not read {blob.name}: {e}")
            continue

    return count


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


def safe_timestamp(value: Any) -> datetime | None:
    """Safely convert to datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    # Try to parse if it's a string or other format
    try:
        if isinstance(value, str):
            # Try common formats
            for fmt in ["%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]:
                try:
                    dt = datetime.strptime(value, fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt
                except ValueError:
                    continue
        return None
    except Exception:
        return None


def flatten_post_record(
    post: dict[str, Any],
    real_replies_count: int,
    ingestion_ts: datetime,
) -> dict[str, Any]:
    """Flatten a post record into a flat dictionary for Parquet."""
    created_at = safe_timestamp(post.get("created_at"))
    updated_at = safe_timestamp(post.get("updated_at"))

    return {
        # Post identification
        "post_id": safe_str(post.get("post_id", "")),
        "country": safe_str(post.get("country", "")),
        "platform": safe_str(post.get("platform", "")),
        "candidate_id": safe_str(post.get("candidate_id", "")),
        # Post metadata
        "created_at": created_at or datetime.now(timezone.utc),
        "replies_count": safe_int(post.get("replies_count")),
        "max_posts_replies": safe_int(post.get("max_posts_replies")),
        "status": safe_str(post.get("status", "")),
        "updated_at": updated_at or datetime.now(timezone.utc),
        # Real replies count (from Parquet)
        "real_replies_count": real_replies_count,
        # Ingestion metadata
        "ingestion_date": ingestion_ts.date(),
        "ingestion_timestamp": ingestion_ts,
    }


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
    parser = argparse.ArgumentParser(
        description="Create consolidated posts table from Firestore and count replies from Parquet"
    )
    parser.add_argument(
        "--bucket",
        required=True,
        help="GCS bucket name",
    )
    parser.add_argument(
        "--project-id",
        default=None,
        help="GCP project ID (default: from environment or ADC)",
    )
    parser.add_argument(
        "--database",
        default="socialnetworks",
        help="Firestore database name (default: socialnetworks)",
    )
    parser.add_argument(
        "--collection",
        default="posts",
        help="Firestore collection name (default: posts)",
    )
    parser.add_argument(
        "--output-dir",
        default="./data/processed",
        help="Local output directory for Parquet files",
    )
    parser.add_argument(
        "--upload",
        action="store_true",
        help="Upload Parquet files to GCS marts/ layer",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't write any files, just show what would be done",
    )
    parser.add_argument(
        "--skip-reply-count",
        action="store_true",
        help="Skip counting replies from Parquet (faster, but real_replies_count will be 0)",
    )

    args = parser.parse_args()

    print("=== Posts Consolidated Table Creation ===")
    print(f"Bucket: {args.bucket}")
    print(f"Project ID: {args.project_id or 'from environment'}")
    print(f"Database: {args.database}")
    print(f"Collection: {args.collection}")
    print(f"Output dir: {args.output_dir}")
    print(f"Upload to GCS: {args.upload}")
    print(f"Dry run: {args.dry_run}")
    print(f"Skip reply count: {args.skip_reply_count}")
    print()

    # Read posts from Firestore
    print("Reading posts from Firestore...")
    posts = read_posts_from_firestore(args.project_id, args.database, args.collection)
    print(f"Found {len(posts)} posts")

    if not posts:
        print("No posts to process")
        return

    # Initialize GCS client
    client = storage.Client(project=args.project_id) if args.project_id else storage.Client()
    bucket = client.bucket(args.bucket)

    # Pre-compute reply counts from all Parquet files (more efficient)
    reply_counts_cache: dict[tuple[str, str], int] | None = None
    if not args.skip_reply_count:
        print("\nPre-computing reply counts from Parquet files...")
        print("  (This may take a while for large datasets)")
        reply_counts_cache = count_all_replies_from_parquet(bucket)
        print(f"  Found {len(reply_counts_cache)} unique (post_id, platform) combinations")

    # Count replies for each post
    ingestion_ts = datetime.now(timezone.utc)
    records = []

    print("\nProcessing posts and counting replies...")
    for i, post in enumerate(posts, 1):
        post_id = post.get("post_id", "")
        platform = post.get("platform", "")

        if not post_id:
            print(f"  [{i}/{len(posts)}] SKIP: Post without post_id")
            continue

        if args.skip_reply_count:
            real_replies_count = 0
        else:
            real_replies_count = count_replies_from_parquet(
                bucket, post_id, platform, reply_counts_cache
            )

        # Flatten post record
        record = flatten_post_record(post, real_replies_count, ingestion_ts)
        records.append(record)

        if i % 100 == 0:
            print(f"    Processed {i}/{len(posts)} posts...")

    print(f"\nTotal records: {len(records)}")

    if args.dry_run:
        print("\n[DRY RUN] No files written")
        print(f"Would create {len(records)} post records")
        return

    # Group records by platform and ingestion date
    # Order: platform first, then ingestion_date (to match BigQuery expectations)
    records_by_partition: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for record in records:
        date_str = record["ingestion_date"].strftime("%Y-%m-%d")
        platform = record["platform"] or "unknown"
        key = (platform, date_str)  # platform first, then date

        if key not in records_by_partition:
            records_by_partition[key] = []
        records_by_partition[key].append(record)

    # Summary
    print(f"\nPartitions: {len(records_by_partition)}")
    for (platform, date_str), partition_records in sorted(records_by_partition.items()):
        print(f"  platform={platform}/ingestion_date={date_str}: {len(partition_records)} records")

    # Write Parquet files
    print("\nWriting Parquet files...")
    output_dir = Path(args.output_dir)
    written_files = []

    for (platform, date_str), partition_records in records_by_partition.items():
        # Create partition directory: platform first, then ingestion_date
        partition_dir = output_dir / "posts" / f"platform={platform}" / f"ingestion_date={date_str}"
        partition_dir.mkdir(parents=True, exist_ok=True)

        # Write Parquet file
        parquet_path = partition_dir / "data.parquet"
        count = records_to_parquet(partition_records, POSTS_SCHEMA, str(parquet_path))

        print(f"  Wrote {count} records to {parquet_path}")
        written_files.append((str(parquet_path), platform, date_str))

    # Upload to GCS if requested
    if args.upload:
        print("\nUploading to GCS...")
        for local_path, platform, date_str in written_files:
            blob_path = f"marts/posts/platform={platform}/ingestion_date={date_str}/data.parquet"
            uri = upload_to_gcs(local_path, args.bucket, blob_path)
            print(f"  Uploaded: {uri}")

    print("\nDone!")

    # Print BigQuery external table hint
    print("\n" + "=" * 60)
    print("To create a BigQuery External Table, run:")
    print("=" * 60)
    print(f"""
CREATE EXTERNAL TABLE `your_project.your_dataset.posts`
WITH PARTITION COLUMNS (
  platform STRING,
  ingestion_date DATE
)
OPTIONS (
  format = 'PARQUET',
  uris = ['gs://{args.bucket}/marts/posts/*'],
  hive_partition_uri_prefix = 'gs://{args.bucket}/marts/posts/'
);
""")


if __name__ == "__main__":
    main()
