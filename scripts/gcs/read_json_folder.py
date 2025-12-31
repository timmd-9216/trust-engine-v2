#!/usr/bin/env python3
"""Read JSON files from a folder (prefix) in a GCS bucket."""

import argparse
import json
import os
import sys

from google.cloud import storage


def _normalize_prefix(prefix: str) -> str:
    if not prefix:
        return ""
    return prefix if prefix.endswith("/") else f"{prefix}/"


def iter_json_blobs(bucket: storage.Bucket, prefix: str):
    for blob in bucket.list_blobs(prefix=prefix):
        if blob.name.endswith(".json") and not blob.name.endswith("/"):
            yield blob


def read_json_folder(bucket_name: str, prefix: str):
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    normalized_prefix = _normalize_prefix(prefix)

    results = []
    for blob in iter_json_blobs(bucket, normalized_prefix):
        payload = blob.download_as_text()
        results.append({"blob": blob.name, "data": json.loads(payload)})
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read JSON files from a folder (prefix) in a GCS bucket.",
    )
    parser.add_argument(
        "--bucket",
        required=True,
        help="GCS bucket name",
    )
    parser.add_argument(
        "--prefix",
        required=True,
        help="Folder prefix in the bucket (e.g., country/platform/candidate_id)",
    )
    parser.add_argument(
        "--write-dir",
        default=None,
        help="Optional local directory to write JSON files to",
    )

    args = parser.parse_args()

    write_dir = args.write_dir
    if write_dir:
        os.makedirs(write_dir, exist_ok=True)

    try:
        records = read_json_folder(args.bucket, args.prefix)
    except Exception as exc:  # noqa: BLE001
        print(f"Error reading JSON from GCS: {exc}", file=sys.stderr)
        return 1

    if not records:
        print("No JSON files found.")
        return 0

    print(f"Found {len(records)} JSON files in gs://{args.bucket}/{_normalize_prefix(args.prefix)}")

    for record in records:
        blob_name = record["blob"]
        data = record["data"]
        if write_dir:
            filename = os.path.basename(blob_name)
            local_path = os.path.join(write_dir, filename)
            with open(local_path, "w", encoding="utf-8") as file_handle:
                json.dump(data, file_handle, ensure_ascii=False, indent=2)
            print(f"Wrote {blob_name} -> {local_path}")
        else:
            print(f"{blob_name}: {json.dumps(data, ensure_ascii=False)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
