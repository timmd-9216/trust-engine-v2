"""youtube_cleanning.py

Starter utilities for loading YouTube keywordpost parquet data from GCS.
"""

from __future__ import annotations

import argparse
from io import BytesIO
from typing import Optional

import pandas as pd


def read_gcs_parquet_folder(
    bucket_name: str,
    prefix: str,
    *,
    project: Optional[str] = None,
) -> pd.DataFrame:
    """Read and concatenate all parquet files from a GCS folder (prefix).

    Requirements:
      pip install google-cloud-storage pyarrow

    Authentication:
      Uses Application Default Credentials (ADC).
      Make sure you ran:
        gcloud auth application-default login
      or set GOOGLE_APPLICATION_CREDENTIALS to a service account key file.
    """
    try:
        from google.cloud import storage  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "Reading from GCS requires google-cloud-storage. "
            "Install with: pip install google-cloud-storage"
        ) from e

    client = storage.Client(project=project)
    bucket = client.bucket(bucket_name)

    blobs = bucket.list_blobs(prefix=prefix)

    frames: list[pd.DataFrame] = []
    for blob in blobs:
        if not blob.name.lower().endswith(".parquet"):
            continue

        raw = blob.download_as_bytes()
        frame = pd.read_parquet(BytesIO(raw))
        frames.append(frame)

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read parquet files from a GCS folder and concatenate them."
    )
    parser.add_argument(
        "--bucket",
        default="trust-prd",
        help="GCS bucket name (default: trust-prd)",
    )
    parser.add_argument(
        "--prefix",
        default="stg/keywordpost/youtube",
        help="GCS prefix/folder (default: stg/keywordpost/youtube)",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="GCP project override (optional)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    df = read_gcs_parquet_folder(args.bucket, args.prefix, project=args.project)
    print(f"Loaded {len(df):,} rows from gs://{args.bucket}/{args.prefix}")


if __name__ == "__main__":
    main()
