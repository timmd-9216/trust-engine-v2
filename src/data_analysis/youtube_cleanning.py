"""youtube_cleanning.py

Starter utilities for loading YouTube keywordpost parquet data from GCS.
"""

from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

import pandas as pd

try:
    import yaml  # type: ignore
except Exception:  # noqa: BLE001
    yaml = None


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


def load_country_config(country: Optional[str], config_dir: str) -> Optional[dict[str, Any]]:
    """Load config/<country>.yaml (or .yml) when available."""
    if not country:
        return None

    cfg_dir = Path(config_dir)
    candidates = [cfg_dir / f"{country}.yaml", cfg_dir / f"{country}.yml"]
    cfg_path = next((p for p in candidates if p.exists()), None)
    if not cfg_path:
        return None

    if yaml is None:
        raise RuntimeError(
            "PyYAML is required to read country config files. Install with: pip install pyyaml."
        )

    with open(cfg_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        return None
    return data


def build_candidate_yaml_frame(cfg: Optional[dict[str, Any]]) -> pd.DataFrame:
    """Build a DataFrame with candidate_id, candidate_name, and youtube_channel_id."""
    if not cfg:
        return pd.DataFrame()
    cand_list = cfg.get("candidates")
    if not isinstance(cand_list, list):
        return pd.DataFrame()
    rows = []
    for cand in cand_list:
        if not isinstance(cand, dict):
            continue
        candidate_id = str(cand.get("candidate_id") or "").strip()
        candidate_name = str(cand.get("name") or "").strip()
        youtube_channel_id = str(cand.get("youtube_channel_id") or "").strip()
        if candidate_id:
            rows.append(
                {
                    "candidate_id": candidate_id,
                    "candidate_name": candidate_name,
                    "youtube_channel_id": youtube_channel_id,
                }
            )
    return pd.DataFrame(rows)


def attach_yaml_info(df: pd.DataFrame, cfg: Optional[dict[str, Any]]) -> pd.DataFrame:
    """Attach YAML candidate info to the dataframe when possible."""
    if df.empty or not cfg:
        return df

    candidate_df = build_candidate_yaml_frame(cfg)
    if candidate_df.empty:
        return df

    if "candidate_id" in df.columns:
        join_col = "candidate_id"
    elif "candidate" in df.columns:
        join_col = "candidate"
        candidate_df = candidate_df.rename(columns={"candidate_id": "candidate"})
    else:
        return df

    return df.merge(candidate_df, on=join_col, how="left")


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
    parser.add_argument(
        "--country",
        default=None,
        help="Country code for YAML config lookup (optional)",
    )
    parser.add_argument(
        "--config-dir",
        default="./config",
        help="Local folder containing country YAML configs (default: ./config)",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    df = read_gcs_parquet_folder(args.bucket, args.prefix, project=args.project)
    cfg = load_country_config(args.country, args.config_dir)
    df = attach_yaml_info(df, cfg)
    print(f"Loaded {len(df):,} rows from gs://{args.bucket}/{args.prefix}")


if __name__ == "__main__":
    main()
