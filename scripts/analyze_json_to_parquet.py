#!/usr/bin/env python3
"""
Analyze JSON files in raw/ and Parquet files in marts/replies/ to understand
why json-to-parquet might not be updating correctly.

This script:
1. Lists JSON files in raw/ with their blob.updated timestamps
2. Lists Parquet files in marts/replies/ with their blob.updated timestamps
3. Reads MAX(ingestion_timestamp) from each Parquet file
4. Compares timestamps to determine which JSONs should be processed
5. Shows what would be skipped vs processed with current logic
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from dotenv import load_dotenv
from google.cloud import storage

try:
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
except ImportError:
    pa = None
    pq = None
    pc = None
    print("WARNING: pyarrow not installed. Cannot read Parquet files.", file=sys.stderr)

# Load environment variables
load_dotenv()


def get_gcs_client(project_id: str | None = None) -> storage.Client:
    """Initialize and return GCS client."""
    if project_id:
        return storage.Client(project=project_id)
    return storage.Client()


def get_parquet_max_ingestion_timestamp(
    bucket: storage.Bucket, date_str: str, platform: str
) -> tuple[datetime | None, datetime | None]:
    """
    Get the maximum ingestion_timestamp from existing Parquet file, if it exists.
    Returns: (max_ingestion_timestamp, blob.updated)
    """
    if not pa or not pq:
        return None, None

    blob_path = f"marts/replies/ingestion_date={date_str}/platform={platform}/data.parquet"
    blob = bucket.blob(blob_path)

    if not blob.exists():
        return None, None

    try:
        blob.reload()
        blob_updated = blob.updated

        # Download Parquet file
        parquet_data = blob.download_as_bytes()
        import io

        parquet_file = io.BytesIO(parquet_data)
        table = pq.read_table(parquet_file)

        # Get max ingestion_timestamp using PyArrow compute
        if pc:
            ingestion_timestamp_col = table.column("ingestion_timestamp")
            if ingestion_timestamp_col is None or len(ingestion_timestamp_col) == 0:
                return None, blob_updated

            max_ts_scalar = pc.max(ingestion_timestamp_col)
            if max_ts_scalar.as_py() is None:
                return None, blob_updated

            max_ts_dt = max_ts_scalar.as_py()
            if isinstance(max_ts_dt, datetime):
                if max_ts_dt.tzinfo is None:
                    max_ts_dt = max_ts_dt.replace(tzinfo=timezone.utc)
                return max_ts_dt, blob_updated

        # Fallback: read all records
        records = table.to_pylist()
        if not records:
            return None, blob_updated
        max_ts = None
        for record in records:
            ts = record.get("ingestion_timestamp")
            if ts is None:
                continue
            if isinstance(ts, datetime):
                if max_ts is None or ts > max_ts:
                    max_ts = ts
            elif hasattr(ts, "as_py"):
                try:
                    ts_dt = ts.as_py()
                    if isinstance(ts_dt, datetime):
                        if max_ts is None or ts_dt > max_ts:
                            max_ts = ts_dt
                except Exception:
                    continue

        if max_ts is None:
            return None, blob_updated
        if max_ts.tzinfo is None:
            max_ts = max_ts.replace(tzinfo=timezone.utc)
        return max_ts, blob_updated

    except Exception as e:
        print(f"ERROR reading Parquet {blob_path}: {e}", file=sys.stderr)
        return None, None


def analyze_json_to_parquet(
    bucket_name: str,
    project_id: str | None = None,
    country: str | None = None,
    platform: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Analyze JSON and Parquet files to understand why json-to-parquet might not be updating."""
    client = get_gcs_client(project_id)
    bucket = client.bucket(bucket_name)

    # Build prefix for JSON files
    prefix = "raw"
    if country:
        prefix = f"{prefix}/{country}"
        if platform:
            prefix = f"{prefix}/{platform}"

    print(f"Analyzing JSON files in: {prefix}/", file=sys.stderr)
    print("Analyzing Parquet files in: marts/replies/", file=sys.stderr)
    print("", file=sys.stderr)

    # List Parquet partitions
    parquet_prefix = "marts/replies/ingestion_date="
    parquet_partitions: dict[tuple[str, str], dict[str, Any]] = {}

    print("Scanning Parquet files...", file=sys.stderr)
    parquet_blobs = bucket.list_blobs(prefix=parquet_prefix)
    for parquet_blob in parquet_blobs:
        if not parquet_blob.name.endswith(".parquet"):
            continue
        parts = parquet_blob.name.split("/")
        if len(parts) >= 4:
            date_part = parts[2].replace("ingestion_date=", "")
            platform_part = parts[3].replace("platform=", "")

            if platform and platform_part != platform:
                continue

            print(f"  Reading Parquet: {parquet_blob.name}...", file=sys.stderr)
            max_ts, blob_updated = get_parquet_max_ingestion_timestamp(
                bucket, date_part, platform_part
            )
            parquet_partitions[(date_part, platform_part)] = {
                "max_ingestion_timestamp": max_ts.isoformat() if max_ts else None,
                "blob_updated": blob_updated.isoformat() if blob_updated else None,
                "path": parquet_blob.name,
            }

    print(f"Found {len(parquet_partitions)} Parquet partitions", file=sys.stderr)
    print("", file=sys.stderr)

    # List JSON files
    print("Scanning JSON files...", file=sys.stderr)
    json_files_by_partition: dict[tuple[str, str], list[dict[str, Any]]] = {}
    blobs = bucket.list_blobs(prefix=prefix)
    json_count = 0

    buffer = timedelta(minutes=5)  # Same buffer as in the code

    for blob in blobs:
        if not blob.name.lower().endswith(".json"):
            continue

        json_count += 1
        if limit and json_count > limit:
            break

        parts = blob.name.split("/")
        path_parts = parts[1:] if parts[0] == "raw" else parts

        # Accept both structures:
        # 1. raw/{country}/{platform}/{candidate_id}/{post_id}.json (len >= 4)
        # 2. raw/{country}/{platform}/{post_id}.json (len == 3)
        # Minimum required: country, platform, post_id (len >= 3)
        if len(path_parts) < 3:
            continue

        blob.reload()
        ingestion_ts = blob.updated or datetime.now(timezone.utc)
        if ingestion_ts.tzinfo is None:
            ingestion_ts = ingestion_ts.replace(tzinfo=timezone.utc)

        # Determine partition
        date_str = ingestion_ts.strftime("%Y-%m-%d")
        platform_from_path = path_parts[1] if len(path_parts) > 1 else ""
        partition_key = (date_str, platform_from_path)

        # Check if should be processed or skipped
        should_process = True
        skip_reason = None
        parquet_max_ts_dt = None

        if partition_key in parquet_partitions:
            parquet_info = parquet_partitions[partition_key]
            max_ts_str = parquet_info.get("max_ingestion_timestamp")
            if max_ts_str:
                parquet_max_ts_dt = datetime.fromisoformat(max_ts_str.replace("Z", "+00:00"))
                # Apply same logic as in json_to_parquet_service
                if ingestion_ts < (parquet_max_ts_dt - buffer):
                    should_process = False
                    skip_reason = f"JSON timestamp {ingestion_ts.isoformat()} is more than 5 minutes older than Parquet max {parquet_max_ts_dt.isoformat()}"

        if partition_key not in json_files_by_partition:
            json_files_by_partition[partition_key] = []

        json_files_by_partition[partition_key].append(
            {
                "path": blob.name,
                "ingestion_ts": ingestion_ts.isoformat(),
                "should_process": should_process,
                "skip_reason": skip_reason,
                "parquet_max_ts": parquet_max_ts_dt.isoformat() if parquet_max_ts_dt else None,
                "time_diff_minutes": (
                    (ingestion_ts - parquet_max_ts_dt).total_seconds() / 60
                    if parquet_max_ts_dt
                    else None
                ),
            }
        )

    # Summary
    total_json_files = sum(len(files) for files in json_files_by_partition.values())
    total_to_process = sum(
        sum(1 for f in files if f["should_process"]) for files in json_files_by_partition.values()
    )
    total_to_skip = total_json_files - total_to_process

    # Convert partition keys (tuples) to strings for JSON serialization
    parquet_partitions_str = {
        f"{date_str}/{platform}": info for (date_str, platform), info in parquet_partitions.items()
    }

    json_files_by_partition_str = {
        f"{date_str}/{platform}": files
        for (date_str, platform), files in json_files_by_partition.items()
    }

    result = {
        "summary": {
            "total_json_files": total_json_files,
            "total_to_process": total_to_process,
            "total_to_skip": total_to_skip,
            "parquet_partitions": len(parquet_partitions),
        },
        "parquet_partitions": parquet_partitions_str,
        "json_files_by_partition": json_files_by_partition_str,
    }

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze JSON and Parquet files to understand json-to-parquet behavior"
    )
    parser.add_argument(
        "--bucket",
        type=str,
        required=True,
        help="GCS bucket name (e.g., trust-prd)",
    )
    parser.add_argument(
        "--project-id",
        type=str,
        default=None,
        help="GCP project ID (default: from GCP_PROJECT_ID env var)",
    )
    parser.add_argument(
        "--country",
        type=str,
        default=None,
        help="Filter by country (optional)",
    )
    parser.add_argument(
        "--platform",
        type=str,
        default=None,
        help="Filter by platform (optional)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of JSON files to analyze (optional)",
    )

    args = parser.parse_args()

    try:
        result = analyze_json_to_parquet(
            bucket_name=args.bucket,
            project_id=args.project_id,
            country=args.country,
            platform=args.platform,
            limit=args.limit,
        )

        print(json.dumps(result, indent=2, default=str))
        return 0
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
