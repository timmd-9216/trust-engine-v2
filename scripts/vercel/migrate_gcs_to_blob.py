#!/usr/bin/env python3
"""Copy objects from a GCS bucket to Vercel Blob, preserving pathnames.

Usage:
    python scripts/vercel/migrate_gcs_to_blob.py \
        --bucket <bucket-name> [--prefix raw] [--dry-run]

Objects that already exist in the Blob store (same pathname) are skipped.
Requires BLOB_READ_WRITE_TOKEN in the environment.
"""

import argparse
import mimetypes
import os
import sys
from pathlib import Path

try:
    from google.cloud import storage
except ImportError:
    sys.exit(
        "google-cloud-storage is not installed. "
        "Install the gcp extra: pip install '.[gcp]' o poetry install --extras gcp"
    )

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from trust_api.scrapping_tools import blob  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", required=True, help="GCS bucket name")
    parser.add_argument("--prefix", default="", help="Only copy objects under this prefix")
    parser.add_argument("--dry-run", action="store_true", help="Print without copying")
    args = parser.parse_args()

    if not args.dry_run and not os.getenv("BLOB_READ_WRITE_TOKEN"):
        sys.exit("ERROR: BLOB_READ_WRITE_TOKEN is not set")

    gcs_client = storage.Client()
    bucket = gcs_client.bucket(args.bucket)

    copied = skipped = errors = 0
    for gcs_blob in bucket.list_blobs(prefix=args.prefix or None):
        path = gcs_blob.name
        try:
            if blob.exists(path):
                skipped += 1
                continue
            if args.dry_run:
                print(f"[dry-run] would copy gs://{args.bucket}/{path}")
                copied += 1
                continue
            data = gcs_blob.download_as_bytes()
            content_type = (
                gcs_blob.content_type or mimetypes.guess_type(path)[0] or "application/octet-stream"
            )
            blob.put(path, data, content_type=content_type)
            copied += 1
            if copied % 50 == 0:
                print(f"{copied} objects copied...")
        except Exception as e:
            errors += 1
            print(f"ERROR copying {path}: {e}", file=sys.stderr)

    print(f"Done. copied={copied} skipped={skipped} errors={errors}")


if __name__ == "__main__":
    main()
