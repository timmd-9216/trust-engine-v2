#!/usr/bin/env python3
"""
Upload locally generated Parquet files to GCS processed layer.

This script uploads Parquet files that were already generated locally
(using json_to_parquet.py without --upload flag) to GCS.

Usage:
    # Upload all Parquet files from local directory
    poetry run python scripts/upload_parquet_to_gcs.py \
      --source-dir ./data/processed \
      --bucket trust-prd

    # Dry run (show what would be uploaded)
    poetry run python scripts/upload_parquet_to_gcs.py \
      --source-dir ./data/processed \
      --bucket trust-prd \
      --dry-run
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

try:
    from google.cloud import storage
except ImportError:
    print("ERROR: google-cloud-storage is required. Install with: poetry add google-cloud-storage")
    sys.exit(1)


def upload_file_to_gcs(
    local_path: str,
    bucket_name: str,
    blob_path: str,
) -> str:
    """Upload a file to GCS and return URI."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_path)

    blob.upload_from_filename(local_path)

    return f"gs://{bucket_name}/{blob_path}"


def find_parquet_files(source_dir: str) -> list[tuple[str, str]]:
    """
    Find all .parquet files in source_dir and return (local_path, gcs_path).

    Expected structure:
    source_dir/replies/platform={platform}/ingestion_date={date}/data.parquet

    Returns:
        List of (local_path, gcs_path) tuples
    """
    source_path = Path(source_dir)
    if not source_path.exists():
        return []

    parquet_files = []

    # Walk through the directory structure
    for parquet_file in source_path.rglob("*.parquet"):
        # Get relative path from source_dir
        relative_path = parquet_file.relative_to(source_path)

        # Convert to GCS path
        # Expected structure: replies/platform=*/ingestion_date=*/data.parquet
        parts = relative_path.parts
        if parts[0] == "replies":
            # Already has replies/ prefix
            gcs_path = f"processed/{relative_path}"
        else:
            # Add processed/replies/ prefix
            gcs_path = f"processed/replies/{relative_path}"

        parquet_files.append((str(parquet_file), gcs_path))

    return parquet_files


def main():
    parser = argparse.ArgumentParser(description="Upload locally generated Parquet files to GCS")
    parser.add_argument(
        "--source-dir",
        default="./data/processed",
        help="Local directory containing Parquet files (default: ./data/processed)",
    )
    parser.add_argument(
        "--bucket",
        required=True,
        help="GCS bucket name",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be uploaded without actually uploading",
    )

    args = parser.parse_args()

    print("=== Upload Parquet to GCS ===")
    print(f"Source directory: {args.source_dir}")
    print(f"Bucket: {args.bucket}")
    print(f"Dry run: {args.dry_run}")
    print()

    # Find all Parquet files
    print("Scanning for Parquet files...")
    parquet_files = find_parquet_files(args.source_dir)

    if not parquet_files:
        print(f"❌ No Parquet files found in {args.source_dir}")
        print("Expected structure: {source_dir}/replies/platform=*/ingestion_date=*/data.parquet")
        sys.exit(1)

    print(f"Found {len(parquet_files)} Parquet file(s)")
    print()

    # Show what will be uploaded
    print("Files to upload:")
    for local_path, gcs_path in sorted(parquet_files):
        size_mb = os.path.getsize(local_path) / (1024 * 1024)
        print(f"  {local_path}")
        print(f"    → gs://{args.bucket}/{gcs_path} ({size_mb:.2f} MB)")

    if args.dry_run:
        print("\n[DRY RUN] No files uploaded")
        return

    # Upload files
    print("\nUploading files...")
    uploaded_count = 0
    total_size_mb = 0

    for local_path, gcs_path in sorted(parquet_files):
        try:
            uri = upload_file_to_gcs(local_path, args.bucket, gcs_path)
            size_mb = os.path.getsize(local_path) / (1024 * 1024)
            total_size_mb += size_mb
            uploaded_count += 1
            print(f"  ✓ Uploaded: {uri} ({size_mb:.2f} MB)")
        except Exception as e:
            print(f"  ❌ Error uploading {local_path}: {e}")
            sys.exit(1)

    print(f"\n✓ Successfully uploaded {uploaded_count} file(s) ({total_size_mb:.2f} MB total)")
    print(f"\nFiles are now available at: gs://{args.bucket}/processed/replies/")


if __name__ == "__main__":
    main()
