"""youtube_cleanning.py

Starter utilities for loading YouTube keywordpost parquet data from GCS.
"""

from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import re
import unicodedata

try:
    import yaml  # type: ignore
except Exception:  # noqa: BLE001
    yaml = None


def _normalize_prefix(prefix: str) -> str:
    if not prefix:
        return ""
    return prefix if prefix.endswith("/") else f"{prefix}/"


def _strip_accents(s: str) -> str:
    """Remove diacritics (accents) from a string."""
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(ch)
    )

def _norm_text(s: Any) -> str:
    """Normalize text for robust 'exact substring' matching (case-insensitive, accent-insensitive)."""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    txt = str(s)
    txt = _strip_accents(txt)
    return txt.casefold()

def _has_any_variation(title: Any, desc: Any, variations: list[str]) -> bool:
    """Return True if any variation appears in title or description (after normalization)."""
    t = _norm_text(title)
    d = _norm_text(desc)
    for v in variations:
        v_norm = _norm_text(v).strip()
        if not v_norm:
            continue
        if v_norm in t or v_norm in d:
            return True
    return False


def read_gcs_parquet_folder(
    bucket_name: str,
    prefix: str,
    country: str,
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

    # Read ONLY the country parquet (e.g., yt_keywordpost_honduras.parquet, yt_keywordpost_bolivia.parquet)
    target = f"{_normalize_prefix(prefix)}yt_keywordpost_{country}.parquet"

    for blob in blobs:
        if blob.name != target:
            continue

        raw = blob.download_as_bytes()
        df = pd.read_parquet(BytesIO(raw))
        print(f"Loaded parquet file: {blob.name}")
        return df

    return pd.DataFrame()


def write_gcs_parquet(
    df: pd.DataFrame,
    bucket_name: str,
    blob_name: str,
    *,
    project: Optional[str] = None,
) -> None:
    """Write a parquet DataFrame to GCS.

    Requirements:
      pip install google-cloud-storage pyarrow

    Authentication:
      Uses Application Default Credentials (ADC).
    """
    try:
        from google.cloud import storage  # type: ignore
    except Exception as e:
        raise RuntimeError(
            "Writing to GCS requires google-cloud-storage. "
            "Install with: pip install google-cloud-storage"
        ) from e

    # Writing parquet requires an engine like pyarrow.
    buf = BytesIO()
    df.to_parquet(buf, index=False)
    buf.seek(0)

    client = storage.Client(project=project)
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(buf.getvalue(), content_type="application/octet-stream")


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
    """Build a DataFrame with candidate_id, candidate_name, youtube_channel_id, and name_variations."""
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
        raw_vars = cand.get("name_variations")
        if isinstance(raw_vars, list):
            variations = [str(x).strip() for x in raw_vars if str(x).strip()]
        else:
            variations = [candidate_name] if candidate_name else []
        youtube_channel_id = str(cand.get("youtube_channel_id") or "").strip()
        if candidate_id:
            rows.append(
                {
                    "candidate_id": candidate_id,
                    "candidate_name": candidate_name,
                    "youtube_channel_id": youtube_channel_id,
                    "candidate_name_variations": variations,
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
        default="honduras",
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
    df = read_gcs_parquet_folder(args.bucket, args.prefix, args.country, project=args.project)

    # Optionally enrich with candidate info from local YAML config (if provided)
    cfg = load_country_config(args.country, args.config_dir)
    df = attach_yaml_info(df, cfg)

    # Ensure report columns exist even when YAML enrichment isn't available
    # (e.g., config file missing or no matching candidate rows).
    required_cols = ["candidate_name"]
    for c in required_cols:
        if c not in df.columns:
            df[c] = pd.NA

    print(f"Loaded {len(df):,} rows from target parquet in gs://{args.bucket}/{args.prefix}")

    cols = [
        "id",
        "url",
        "channel_id",
        "channel_title",
        "candidate_id",
        "candidate_name",
        "title",
        "description",
        "tags",
        "view_count",
    ]

    # --- Non-relevant videos report ---
    # Rows where title+description do NOT contain any of the candidate's name_variations.

    VIEWS_THRESHOLD = 100

    nonrel_cols = ["url", "candidate_id", "candidate_name", "title", "description"]

    df_nonrel = df.copy()

    # Ensure required columns exist
    for c in ["title", "description", "url", "candidate_id", "candidate_name", "candidate_name_variations"]:
        if c not in df_nonrel.columns:
            df_nonrel[c] = pd.NA

    # If YAML didn't attach variations, fallback to candidate_name
    def _fallback_vars(row: pd.Series) -> list[str]:
        v = row.get("candidate_name_variations")
        if isinstance(v, list) and len(v) > 0:
            return v
        name_val = row.get("candidate_name")
        if name_val is None or pd.isna(name_val):
            return []
        name = str(name_val).strip()
        return [name] if name else []

    df_nonrel["candidate_name_variations"] = df_nonrel.apply(_fallback_vars, axis=1)

    mask_has_name = df_nonrel.apply(
        lambda r: _has_any_variation(r["title"], r["description"], r["candidate_name_variations"]),
        axis=1,
    )

    # Mark relevant videos with few views
    df_nonrel["_views"] = pd.to_numeric(df_nonrel.get("view_count"), errors="coerce").fillna(0).astype(int)
    df_nonrel["_is_relevant_few_views"] = mask_has_name & (df_nonrel["_views"] < VIEWS_THRESHOLD)
    df_nonrel["_is_relevant_strong"] = mask_has_name & (df_nonrel["_views"] >= VIEWS_THRESHOLD)

    # --- Candidate relevance summary ("main report") ---
    # Counts are computed on the full df_nonrel (i.e., all rows) using the same name_variations logic.
    # relevant_videos_count: videos with any name_variations match and views >= threshold
    # relevant_few_views_count: videos with any name_variations match but views < threshold
    # non_relevant_videos_count: videos without match
    # non_relevant_pct: non_relevant_videos_count / video_ids_count
    id_col = "id" if "id" in df_nonrel.columns else None

    def _unique_count(series: pd.Series) -> int:
        return int(series.nunique(dropna=True))

    df_counts = df_nonrel.copy()
    df_counts["_is_relevant"] = mask_has_name

    grp = df_counts.groupby(["candidate_id", "candidate_name"], dropna=False)

    def _count_block(g: pd.DataFrame) -> pd.Series:
        if id_col and id_col in g.columns:
            total = _unique_count(g[id_col])
            nonrel = _unique_count(g.loc[~g["_is_relevant"], id_col])
        else:
            total = int(len(g))
            nonrel = int((~g["_is_relevant"]).sum())
        return pd.Series(
            {
                "video_ids_count": total,
                "relevant_videos_count": int(
                    _unique_count(g.loc[g["_is_relevant_strong"], id_col])
                    if id_col and id_col in g.columns
                    else g["_is_relevant_strong"].sum()
                ),
                "relevant_few_views_count": int(
                    _unique_count(g.loc[g["_is_relevant_few_views"], id_col])
                    if id_col and id_col in g.columns
                    else g["_is_relevant_few_views"].sum()
                ),
                "non_relevant_videos_count": nonrel,
            }
        )

    summary = grp.apply(_count_block).reset_index()
    summary["relevant_pct"] = summary.apply(
        lambda r: (r["relevant_videos_count"] / r["video_ids_count"]) if r["video_ids_count"] else 0.0,
        axis=1,
    )

    summary = summary[
        [
            "candidate_id",
            "candidate_name",
            "video_ids_count",
            "relevant_videos_count",
            "relevant_few_views_count",
            "non_relevant_videos_count",
            "relevant_pct",
        ]
    ].sort_values(["candidate_id"])

    out_summary = f"./out/yt_keywordpost_{args.country}_relevance_summary.csv"
    summary.to_csv(out_summary, index=False)

    # --- Save filtered parquet to GCS (ONLY the rows counted as relevant_videos_count) ---
    # i.e., rows where name_variations match AND views >= threshold.
    filtered_prefix = "stg/keywordpost_filtered/youtube"
    filtered_blob = f"{filtered_prefix}/yt_keywordpost_ft_{args.country}.parquet"

    df_filtered = df_nonrel.loc[df_nonrel["_is_relevant_strong"]].copy()

    # Write to GCS
    write_gcs_parquet(df_filtered, args.bucket, filtered_blob, project=args.project)
    print(
        f"\nUploaded filtered parquet (relevant_videos_count rows): "
        f"gs://{args.bucket}/{filtered_blob} (rows: {len(df_filtered):,})"
    )

    df_nonrel = df_nonrel.loc[~mask_has_name, nonrel_cols].copy()

    out_nonrel = f"./out/yt_keywordpost_{args.country}_non_relevant.csv"
    df_nonrel.to_csv(out_nonrel, index=False)
    print(f"\nExported NON-RELEVANT report (no name_variations match in title/description): {out_nonrel}")
    print(f"Non-relevant rows: {len(df_nonrel):,} (of {len(df):,})")


if __name__ == "__main__":
    main()
