#!/usr/bin/env python3
"""Read JSON files from a folder (prefix) in a GCS bucket."""

import argparse
import json
import os
import sys
import subprocess

import csv
import re

from google.cloud import storage
from collections import Counter
from typing import Optional

from .read_data import read_google_sheet

from pathlib import Path
from typing import Any, Dict, List, Tuple

# --- YAML config support ---
try:
    import yaml  # type: ignore
except Exception:  # noqa: BLE001
    yaml = None


def _normalize_prefix(prefix: str) -> str:
    if not prefix:
        return ""
    return prefix if prefix.endswith("/") else f"{prefix}/"


# --- YAML config helpers ---
def _try_load_country_config(country: Optional[str], config_dir: str) -> Optional[Dict[str, Any]]:
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
            "PyYAML is required to read country config files. Install with: pip install pyyaml (or add to poetry dependencies)."
        )

    with open(cfg_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        return None
    return data



def _candidate_name_map_from_config(cfg: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Build candidate_id -> name mapping from loaded YAML config."""
    if not cfg:
        return {}
    cand_list = cfg.get("candidates")
    if not isinstance(cand_list, list):
        return {}
    out: Dict[str, str] = {}
    for c in cand_list:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("candidate_id") or "").strip()
        name = str(c.get("name") or "").strip()
        if cid:
            out[cid] = name
    return out


# --- Output organization helpers ---

def _resolve_country_lower(args_country: Optional[str], cfg: Optional[Dict[str, Any]]) -> str:
    if cfg and isinstance(cfg.get("country"), str) and cfg.get("country").strip():
        return str(cfg.get("country")).strip().lower()
    return str(args_country or "").strip().lower()


def _resolve_platform_lower(args_platform: Optional[str], parts: Optional[List[str]] = None) -> str:
    if args_platform:
        return str(args_platform).strip().lower()
    if parts and len(parts) >= 3 and parts[0] == "raw":
        return str(parts[2]).strip().lower()
    return ""


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _build_reports_paths(out_base: str, country: str, platform: str) -> Dict[str, str]:
    """Return folders for reports and candidates under out_base/<country>/<platform>/"""
    base = os.path.join(out_base, country, platform)
    reports_dir = os.path.join(base, "reports")
    candidates_dir = os.path.join(base, "candidates")
    _ensure_dir(reports_dir)
    _ensure_dir(candidates_dir)
    return {
        "base": base,
        "reports_dir": reports_dir,
        "candidates_dir": candidates_dir,
        "report1": os.path.join(reports_dir, "report1.csv"),
        "report2": os.path.join(reports_dir, "candidate_summary.csv"),
        "report_instagram": os.path.join(reports_dir, "candidate_summary_instagram.csv"),
        "report_youtube": os.path.join(reports_dir, "candidate_summary_youtube.csv"),
        "report1_users": os.path.join(reports_dir, "report1_users.csv"),
    }


def _write_candidate_summary_csv(candidates_dir: str, row: Dict[str, Any]) -> None:
    # Intentionally disabled: do not create one-line per-candidate CSVs.
    # Keep candidates/ folders empty.
    return



def _extract_items(json_obj: Any) -> List[Dict[str, Any]]:
    # Handles schema variants:
    # - list[dict]
    # - {"data":[...]}
    # - {"results":[...]}
    if isinstance(json_obj, list):
        return [x for x in json_obj if isinstance(x, dict)]
    if isinstance(json_obj, dict):
        if isinstance(json_obj.get("data"), list):
            return [x for x in json_obj["data"] if isinstance(x, dict)]
        if isinstance(json_obj.get("results"), list):
            return [x for x in json_obj["results"] if isinstance(x, dict)]
        return [json_obj]
    return []


# --- Username helpers for YAML/candidate matching ---
def _norm_username(u: Any) -> str:
    u = str(u or "").strip()
    if u.startswith("@"):  # allow YAML values like @handle
        u = u[1:]
    return u.lower()


def _item_username(item: Dict[str, Any]) -> str:
    # Common schema: screen_name at top-level
    if item.get("screen_name"):
        return _norm_username(item.get("screen_name"))
    # Sometimes nested user object
    user = item.get("user")
    if isinstance(user, dict):
        if user.get("screen_name"):
            return _norm_username(user.get("screen_name"))
        if user.get("username"):
            return _norm_username(user.get("username"))
    # Fallbacks
    if item.get("username"):
        return _norm_username(item.get("username"))
    if item.get("author_username"):
        return _norm_username(item.get("author_username"))
    return ""


def _count_items_by_username(records: List[Dict[str, Any]], username: str) -> int:
    target = _norm_username(username)
    if not target:
        return 0
    count = 0
    for record in records:
        for item in _extract_items(record.get("data")):
            if _item_username(item) == target:
                count += 1
    return count


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


# Helper: read a single JSON blob from GCS
def read_single_json_blob(bucket_name: str, blob_name: str) -> Dict[str, Any]:
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    payload = blob.download_as_text(encoding="utf-8")
    return {"blob": blob_name, "data": json.loads(payload)}


def read_json_by_candidate_folder(bucket_name: str, base_prefix: str):
    """
    Read JSONs from gs://bucket/base_prefix/** grouped by the first subfolder name.

    Skips JSON files that are directly under base_prefix (i.e., no subfolder).
    Each immediate subfolder is treated as a candidate_id "unit" for reporting.
    """
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    normalized_base = _normalize_prefix(base_prefix)

    grouped = {}
    for blob in iter_json_blobs(bucket, normalized_base):
        # Example blob.name: raw/honduras/twitter/09sosa/part-000.json
        remainder = blob.name[len(normalized_base) :] if blob.name.startswith(normalized_base) else ""
        if not remainder or "/" not in remainder:
            # JSON directly under base prefix (or unexpected): skip
            continue

        candidate_id = remainder.split("/", 1)[0].strip()
        if not candidate_id:
            continue

        payload = blob.download_as_text()
        grouped.setdefault(candidate_id, []).append({"blob": blob.name, "data": json.loads(payload)})

    return grouped


def compute_metrics_from_records(records):
    metrics = {
        "files": 0,
        "items": 0,
        "tweets": 0,
        "replies": 0,
        "retweets": 0,
        "quotes": 0,
        "media_items": 0,
        "sum_reply_count": 0,
        "sum_retweet_count": 0,
        "sum_quote_count": 0,
        "sum_favorite_count": 0,
    }

    for record in records:
        metrics["files"] += 1
        items = _extract_items(record["data"])

        for item in items:
            metrics["items"] += 1

            # Retweet detection
            is_retweet = False
            if item.get("retweeted_status_id_str") or item.get("retweeted_status_screen_name"):
                is_retweet = True
            elif item.get("full_text", "").startswith("RT @"):
                is_retweet = True
            elif item.get("retweeted") is True and item.get("is_quote_status") is False:
                is_retweet = True

            if is_retweet:
                metrics["retweets"] += 1
            else:
                metrics["tweets"] += 1

            if item.get("in_reply_to_status_id_str") or item.get("in_reply_to_user_id_str") or item.get("in_reply_to_screen_name"):
                metrics["replies"] += 1

            if item.get("is_quote_status") is True:
                metrics["quotes"] += 1

            media_count = item.get("media_count", 0)
            entities_media = False
            entities = item.get("entities")
            if entities and isinstance(entities, dict):
                media = entities.get("media")
                if media and isinstance(media, list) and len(media) > 0:
                    entities_media = True

            if (media_count and media_count > 0) or entities_media:
                metrics["media_items"] += 1

            def safe_int(val):
                try:
                    return int(val)
                except Exception:  # noqa: E722
                    return 0

            metrics["sum_reply_count"] += safe_int(item.get("reply_count", 0))
            metrics["sum_retweet_count"] += safe_int(item.get("retweet_count", 0))
            metrics["sum_quote_count"] += safe_int(item.get("quote_count", 0))
            metrics["sum_favorite_count"] += safe_int(item.get("favorite_count", 0))

    return metrics


# --- Instagram metrics ---

def compute_instagram_metrics_from_records(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute metrics for Instagram comment/reply items in candidate subfolder JSONs."""
    metrics: Dict[str, Any] = {
        "files": 0,
        "items": 0,
        "unique_users": 0,
        "sum_child_comment_count": 0,
        "sum_comment_like_count": 0,
    }

    def safe_int(val: Any) -> int:
        try:
            if val is None:
                return 0
            return int(val)
        except Exception:
            return 0

    users = set()
    for record in records:
        metrics["files"] += 1
        items = _extract_items(record.get("data"))
        for item in items:
            metrics["items"] += 1
            uname = _norm_username(item.get("username") or "")
            if uname:
                users.add(uname)
            metrics["sum_child_comment_count"] += safe_int(item.get("child_comment_count", 0))
            metrics["sum_comment_like_count"] += safe_int(item.get("comment_like_count", 0))

    metrics["unique_users"] = len(users)
    return metrics


def compute_instagram_home_metrics_from_records(records: List[Dict[str, Any]], instagram_username: str) -> Dict[str, Any]:
    """Compute own-post metrics from Instagram home JSON records (dict with data list)."""
    out: Dict[str, Any] = {
        "own_posts_raw": 0,
        "own_posts": 0,
        "sum_post_like_count": 0,
        "sum_post_comment_count": 0,
    }

    def safe_int(val: Any) -> int:
        try:
            if val is None:
                return 0
            return int(val)
        except Exception:
            return 0

    target = _norm_username(instagram_username)
    for record in records:
        for item in _extract_items(record.get("data")):
            out["own_posts_raw"] += 1
            uname = _norm_username(item.get("username") or "")
            if target and uname == target:
                out["own_posts"] += 1
            out["sum_post_like_count"] += safe_int(item.get("like_count", 0))
            out["sum_post_comment_count"] += safe_int(item.get("comment_count", 0))

    return out


# --- YouTube metrics ---

def _parse_iso8601_duration_seconds(duration: Any) -> int:
    """Parse a subset of ISO8601 durations like PT49M50S, PT1M31S, PT40S, PT1H2M3S."""
    s = str(duration or "").strip()
    if not s:
        return 0
    m = re.match(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$", s)
    if not m:
        return 0
    h = int(m.group(1) or 0)
    mn = int(m.group(2) or 0)
    sec = int(m.group(3) or 0)
    return h * 3600 + mn * 60 + sec


def compute_youtube_metrics_from_records(records: List[Dict[str, Any]], youtube_channel_id: str) -> Dict[str, Any]:
    """Compute metrics for YouTube videos in candidate subfolder JSONs."""
    def safe_int(val: Any) -> int:
        try:
            if val is None or val == "":
                return 0
            return int(val)
        except Exception:
            return 0

    target_ch = str(youtube_channel_id or "").strip()

    out: Dict[str, Any] = {
        "files": 0,
        "videos": 0,
        "videos_own": 0,
        "unique_channels": 0,
        "sum_view_count": 0,
        "sum_like_count": 0,
        "sum_comment_count": 0,
        "avg_duration_seconds": 0,
        "languages": "",
    }

    channels = set()
    langs = set()
    dur_sum = 0

    for record in records:
        out["files"] += 1
        items = _extract_items(record.get("data"))
        for item in items:
            out["videos"] += 1
            ch = str(item.get("channel_id") or "").strip()
            if ch:
                channels.add(ch)
            if target_ch and ch == target_ch:
                out["videos_own"] += 1

            out["sum_view_count"] += safe_int(item.get("view_count", 0))
            out["sum_like_count"] += safe_int(item.get("like_count", 0))
            out["sum_comment_count"] += safe_int(item.get("comment_count", 0))

            dur_sum += _parse_iso8601_duration_seconds(item.get("duration"))

            lang = str(item.get("language") or "").strip()
            if lang:
                langs.add(lang)

    out["unique_channels"] = len(channels)
    out["avg_duration_seconds"] = int(dur_sum / out["videos"]) if out["videos"] else 0

    # Keep a stable, short languages string
    if langs:
        out["languages"] = ",".join(sorted(langs)[:5])
    else:
        out["languages"] = ""

    return out


# --- CSV/description helpers ---
def _sanitize_text(s: Any, max_len: int = 80) -> str:
    if s is None:
        return ""
    # normalize whitespace and strip newlines
    text = str(s).replace("\n", " ").replace("\r", " ").strip()
    # drop non-ascii (emojis / weird chars) for terminal/csv stability
    text = text.encode("ascii", "ignore").decode("ascii", "ignore")
    # collapse spaces
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text

def pick_example_tweet_url(records) -> str:
    for record in records:
        items = _extract_items(record["data"])
        for item in items:
            url = item.get("tweet_url")
            if url:
                return str(url)
    return ""


# --- User breakdown helper ---
def compute_user_breakdown(records, *, candidate: str, source: str) -> List[Dict[str, Any]]:
    """
    Return per-user rows with tweet metrics for the given record set.
    A "user" is identified by user_id_str when present, else by screen_name.
    """
    buckets: Dict[str, Dict[str, Any]] = {}

    def safe_int(val):
        try:
            return int(val)
        except Exception:  # noqa: E722
            return 0

    for record in records:
        items = _extract_items(record["data"])
        for item in items:
            user_id = str(item.get("user_id_str") or "").strip()
            screen = str(item.get("screen_name") or "").strip()
            key = user_id or screen or "(missing)"

            if key not in buckets:
                buckets[key] = {
                    "candidate": candidate,
                    "source": source,
                    "user_id_str": user_id,
                    "screen_name": screen,
                    "name": _sanitize_text(item.get("name") or "", max_len=40),
                    "lang": str(item.get("lang") or "").strip(),
                    "description_short": _sanitize_text(item.get("description") or "", max_len=80),
                    "example_tweet_url": str(item.get("tweet_url") or ""),
                    "files": 0,
                    "items": 0,
                    "tweets": 0,
                    "replies": 0,
                    "retweets": 0,
                    "quotes": 0,
                    "media_items": 0,
                    "sum_reply_count": 0,
                    "sum_retweet_count": 0,
                    "sum_quote_count": 0,
                    "sum_favorite_count": 0,
                }

            b = buckets[key]
            b["items"] += 1

            # Retweet detection (same rules as candidate-level)
            is_retweet = False
            if item.get("retweeted_status_id_str") or item.get("retweeted_status_screen_name"):
                is_retweet = True
            elif item.get("full_text", "").startswith("RT @"):
                is_retweet = True
            elif item.get("retweeted") is True and item.get("is_quote_status") is False:
                is_retweet = True

            if is_retweet:
                b["retweets"] += 1
            else:
                b["tweets"] += 1

            if item.get("in_reply_to_status_id_str") or item.get("in_reply_to_user_id_str") or item.get("in_reply_to_screen_name"):
                b["replies"] += 1

            if item.get("is_quote_status") is True:
                b["quotes"] += 1

            media_count = item.get("media_count", 0)
            entities_media = False
            entities = item.get("entities")
            if entities and isinstance(entities, dict):
                media = entities.get("media")
                if media and isinstance(media, list) and len(media) > 0:
                    entities_media = True

            if (media_count and media_count > 0) or entities_media:
                b["media_items"] += 1

            b["sum_reply_count"] += safe_int(item.get("reply_count", 0))
            b["sum_retweet_count"] += safe_int(item.get("retweet_count", 0))
            b["sum_quote_count"] += safe_int(item.get("quote_count", 0))
            b["sum_favorite_count"] += safe_int(item.get("favorite_count", 0))

            # keep first example url
            if not b["example_tweet_url"] and item.get("tweet_url"):
                b["example_tweet_url"] = str(item.get("tweet_url"))

    # Approx files: count distinct blobs
    blob_names = {r.get("blob") for r in records if r.get("blob")}
    files_n = len(blob_names)
    for b in buckets.values():
        b["files"] = files_n

    rows = list(buckets.values())
    rows.sort(key=lambda r: r["items"], reverse=True)
    return rows


# --- Description breakdown helpers ---
def count_items_by_description(records):
    """
    Count items grouped by 'description' field and also track most common name/lang per description.
    Useful to detect mixed / dirty candidate data.
    """
    counts: Dict[str, Dict[str, Any]] = {}
    for record in records:
        items = _extract_items(record["data"])
        for item in items:
            desc = item.get("description") or "(missing)"
            desc = str(desc).replace("\n", " ").replace("\r", " ").strip()

            name = item.get("name") or "(missing)"
            name = str(name).replace("\n", " ").replace("\r", " ").strip()

            lang = item.get("lang") or "(missing)"
            lang = str(lang).strip()

            if desc not in counts:
                counts[desc] = {"count": 0, "names": Counter(), "langs": Counter()}

            counts[desc]["count"] += 1
            counts[desc]["names"][name] += 1
            counts[desc]["langs"][lang] += 1

    return counts


def dominant_description_short(records) -> str:
    desc_counts = count_items_by_description(records)
    if not desc_counts:
        return ""
    # pick the most frequent description
    desc, meta = max(desc_counts.items(), key=lambda kv: kv[1]["count"])
    return _sanitize_text(desc, max_len=80)


def write_csv(path: str, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            # ensure only declared fields
            w.writerow({k: r.get(k, "") for k in fieldnames})


def _pick_id_column(df) -> Optional[str]:
    """Pick a likely candidate-id column from the Honduras sheet."""
    candidates = [
        "candidate_id",
        "candidate",
        "id",
        "handle",
        "twitter_handle",
        "twitter",
        "account",
        "username",
    ]
    cols_lower = {str(c).strip().lower(): str(c) for c in df.columns}
    for key in candidates:
        if key in cols_lower:
            return cols_lower[key]
    return None


def print_metrics_table(title: str, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        print(f"\n=== {title} ===")
        print("(no rows)")
        return
    columns = [
        "candidate",
        "candidate_name",
        "twitter_username",
        "own_posts_raw",
        "own_posts",
        "own_posts_retrieved",
        "items",
        "tweets",
        "replies",
        "retweets",
        "quotes",
        "media_items",
        "sum_reply_count",
        "sum_retweet_count",
        "sum_quote_count",
        "sum_favorite_count",
    ]

    # compute widths
    widths = {c: len(c) for c in columns}
    for r in rows:
        for c in columns:
            widths[c] = max(widths[c], len(str(r.get(c, ""))))

    print(f"\n=== {title} ===")
    header = "  ".join(str(c).ljust(widths[c]) for c in columns)
    sep = "  ".join("-" * widths[c] for c in columns)
    print(header)
    print(sep)
    for r in rows:
        line = "  ".join(str(r.get(c, "")).ljust(widths[c]) for c in columns)
        print(line)


def print_metrics_table_custom(title: str, rows: List[Dict[str, Any]], columns: List[str]) -> None:
    if not rows:
        print(f"\n=== {title} ===")
        print("(no rows)")
        return

    widths = {c: len(c) for c in columns}
    for r in rows:
        for c in columns:
            widths[c] = max(widths[c], len(str(r.get(c, ""))))

    print(f"\n=== {title} ===")
    header = "  ".join(str(c).ljust(widths[c]) for c in columns)
    sep = "  ".join("-" * widths[c] for c in columns)
    print(header)
    print(sep)
    for r in rows:
        line = "  ".join(str(r.get(c, "")).ljust(widths[c]) for c in columns)
        print(line)


def print_description_breakdown(candidate: str, desc_counts: Dict[str, Any]):
    print(f"\n-- Description breakdown for {candidate} --")
    if not desc_counts:
        print("(no descriptions)")
        return

    total = sum(v["count"] for v in desc_counts.values())
    print(f"Total items: {total} | Unique descriptions: {len(desc_counts)}")

    # Sort by count descending
    sorted_items = sorted(desc_counts.items(), key=lambda kv: kv[1]["count"], reverse=True)

    for desc, meta in sorted_items:
        count = meta["count"]
        pct = (count / total) * 100 if total else 0

        top_name = meta["names"].most_common(1)[0][0] if meta.get("names") else "(missing)"
        top_lang = meta["langs"].most_common(1)[0][0] if meta.get("langs") else "(missing)"

        clean_desc = desc.replace("\n", " ").replace("\r", " ")
        clean_name = str(top_name).replace("\n", " ").replace("\r", " ")

        print(f"[{count:>4}] ({pct:5.1f}%) lang={top_lang:<8} name={clean_name[:40]:<40} desc={clean_desc[:120]}")


def read_json_files_directly_under_prefix(bucket_name: str, base_prefix: str):
    """
    Return records for JSON files directly under base_prefix (no subfolder),
    and skip any JSONs under subfolders.
    """
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    normalized_base = _normalize_prefix(base_prefix)

    records = []
    for blob in iter_json_blobs(bucket, normalized_base):
        remainder = blob.name[len(normalized_base):] if blob.name.startswith(normalized_base) else ""
        if not remainder or "/" in remainder:
            continue
        payload = blob.download_as_text()
        records.append({"blob": blob.name, "data": json.loads(payload)})
    return records


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
        default=None,
        help="Folder prefix in the bucket (e.g., country/platform/candidate_id). Required unless --country and --platform are provided.",
    )
    parser.add_argument(
        "--country",
        default=None,
        help="Country name used to read the Google Sheet tab and build GCS prefixes (e.g., honduras)",
    )
    parser.add_argument(
        "--platform",
        default=None,
        help="Platform name used to build GCS prefixes (twitter|instagram|youtube). Use 'all' to run all three, or a comma-separated list.",
    )
    parser.add_argument(
        "--spreadsheet-id",
        default="1SWsFfxcZbU24bn0pqcP6JyNrBvRmSHBVj02HLNv--Uk",
        help="Google Spreadsheet ID (default: project sheet)",
    )
    parser.add_argument(
        "--google-creds-json",
        default=os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"),
        help="Service account JSON content (string). If not provided, tries public CSV export. You can also set env var GOOGLE_SERVICE_ACCOUNT_JSON.",
    )
    parser.add_argument(
        "--write-dir",
        default=None,
        help="Optional local directory to write JSON files to",
    )
    parser.add_argument(
        "--out-csv",
        default=None,
        help="Optional output CSV path. If ends with .csv, writes *_report1.csv and *_report2.csv next to it; otherwise treated as an output directory.",
    )
    parser.add_argument(
        "--blob",
        default=None,
        help="Exact GCS object name (blob) to read a single JSON file (e.g., raw/honduras/twitter/2512161744_tw_ownpost_hnd01monc.json). If set, produces a detail CSV and exits.",
    )
    parser.add_argument(
        "--detail-csv",
        default="./detail.csv",
        help="Output path for the detail CSV when --blob is used.",
    )

    parser.add_argument(
        "--config-dir",
        default="config",
        help="Local folder containing country YAML configs (default: ./config)",
    )

    args = parser.parse_args()

    if not args.blob and (not (args.country and args.platform) and not args.prefix):
        parser.error("--prefix is required unless --country and --platform are provided, or --blob is provided")

    # Multi-platform convenience: --platform all or comma-separated list
    if args.country and args.platform and not args.blob and not args.prefix:
        plat_raw = str(args.platform).strip()
        plat_lower = plat_raw.lower()
        if plat_lower == "all" or "," in plat_raw:
            if plat_lower == "all":
                platforms = ["twitter", "instagram", "youtube"]
            else:
                platforms = [p.strip().lower() for p in plat_raw.split(",") if p.strip()]

            base_cmd = [
                sys.executable,
                "-m",
                "src.data_analysis.read_json_folder",
                "--bucket",
                str(args.bucket),
                "--country",
                str(args.country),
                "--config-dir",
                str(args.config_dir),
                "--out-csv",
                str(args.out_csv) if args.out_csv is not None else "",
            ]
            # Remove empty --out-csv if not provided
            if args.out_csv is None:
                base_cmd = [c for c in base_cmd if c not in ("--out-csv", "")]

            # Optional passthroughs
            if args.google_creds_json:
                base_cmd += ["--google-creds-json", str(args.google_creds_json)]
            if args.write_dir:
                base_cmd += ["--write-dir", str(args.write_dir)]
            if args.spreadsheet_id:
                base_cmd += ["--spreadsheet-id", str(args.spreadsheet_id)]

            rc = 0
            for p in platforms:
                cmd = base_cmd + ["--platform", p]
                print(f"\n=== RUNNING PLATFORM: {p} ===")
                proc = subprocess.run(cmd)
                if proc.returncode != 0:
                    rc = proc.returncode
                    break

            return 0 if rc == 0 else 1

    write_dir = args.write_dir
    if write_dir:
        os.makedirs(write_dir, exist_ok=True)

    try:
        if args.blob:
            record = read_single_json_blob(args.bucket, args.blob)
            records = [record]
            items = _extract_items(record["data"])

            def is_retweet_item(item: Dict[str, Any]) -> bool:
                if item.get("retweeted_status_id_str") or item.get("retweeted_status_screen_name"):
                    return True
                if str(item.get("full_text", "")).startswith("RT @"):
                    return True
                if item.get("retweeted") is True and item.get("is_quote_status") is False:
                    return True
                return False

            def has_media_item(item: Dict[str, Any]) -> int:
                media_count = item.get("media_count", 0)
                entities = item.get("entities")
                if entities and isinstance(entities, dict):
                    media = entities.get("media")
                    if media and isinstance(media, list) and len(media) > 0:
                        return 1
                try:
                    return 1 if int(media_count) > 0 else 0
                except Exception:  # noqa: E722
                    return 0

            def safe_int(val: Any) -> int:
                try:
                    return int(val)
                except Exception:  # noqa: E722
                    return 0

            rows = []
            for item in items:
                is_reply = 1 if (item.get("in_reply_to_status_id_str") or item.get("in_reply_to_user_id_str") or item.get("in_reply_to_screen_name")) else 0
                is_quote = 1 if item.get("is_quote_status") is True else 0
                is_retweet = 1 if is_retweet_item(item) else 0
                text_short = _sanitize_text(item.get("full_text") or item.get("text") or "", max_len=180)
                rows.append({
                    "tweet_url": str(item.get("tweet_url") or ""),
                    "created_at": str(item.get("created_at") or ""),
                    "text_short": text_short,
                    "reply_count": safe_int(item.get("reply_count", 0)),
                    "retweet_count": safe_int(item.get("retweet_count", 0)),
                    "quote_count": safe_int(item.get("quote_count", 0)),
                    "favorite_count": safe_int(item.get("favorite_count", 0)),
                    "lang": str(item.get("lang") or ""),
                    "is_reply": is_reply,
                    "is_retweet": is_retweet,
                    "is_quote": is_quote,
                    "has_media": has_media_item(item),
                })

            detail_cols = [
                "tweet_url",
                "created_at",
                "text_short",
                "reply_count",
                "retweet_count",
                "quote_count",
                "favorite_count",
                "lang",
                "is_reply",
                "is_retweet",
                "is_quote",
                "has_media",
            ]
            write_csv(args.detail_csv, rows, detail_cols)
            print(f"Detail items: {len(items)}")
            print(f"Wrote detail CSV: {args.detail_csv}")
            return 0

        if args.country and args.platform:
            sheet_tab = args.country.title()
            cfg = _try_load_country_config(args.country, args.config_dir)
            name_map = _candidate_name_map_from_config(cfg)
            cfg_candidates = (cfg or {}).get("candidates") if isinstance(cfg, dict) else None
            country_lower = _resolve_country_lower(args.country, cfg)
            platform_lower = _resolve_platform_lower(args.platform)

            # Preserve candidate order as defined in YAML
            yaml_order = []
            if isinstance(cfg_candidates, list):
                for c in cfg_candidates:
                    if isinstance(c, dict) and c.get("candidate_id"):
                        yaml_order.append(str(c.get("candidate_id")).strip())
            order_index = {cid: i for i, cid in enumerate(yaml_order)}

            # --- Instagram candidate summary ---
            if platform_lower == "instagram":
                if not (cfg and isinstance(cfg_candidates, list) and len(cfg_candidates) > 0):
                    raise RuntimeError("Instagram reporting requires YAML candidates (config/<country>.yaml)")

                base_prefix = f"raw/{args.country}/{args.platform}/"
                direct_home_records = read_json_files_directly_under_prefix(args.bucket, base_prefix)

                ig_columns = [
                    "candidate",
                    "candidate_name",
                    "instagram_username",
                    "own_posts_raw",
                    "own_posts",
                    "own_posts_retrieved",
                    "items",
                    "unique_users",
                    "sum_child_comment_count",
                    "sum_comment_like_count",
                    "sum_post_like_count",
                    "sum_post_comment_count",
                ]

                rows: List[Dict[str, Any]] = []
                for c in cfg_candidates:
                    if not isinstance(c, dict):
                        continue
                    candidate_id_str = str(c.get("candidate_id") or "").strip()
                    if not candidate_id_str:
                        continue
                    candidate_name = str(c.get("name") or "").strip()
                    instagram_username = str(c.get("instagram_username") or "").strip()

                    # Candidate subfolder JSONs (comments/replies)
                    prefix = f"raw/{args.country}/{args.platform}/{candidate_id_str}"
                    records = read_json_folder(args.bucket, prefix)

                    if write_dir:
                        for record in records:
                            blob_name = record["blob"]
                            data = record["data"]
                            filename = os.path.basename(blob_name)
                            candidate_out_dir = os.path.join(write_dir, country_lower, platform_lower, candidate_id_str)
                            os.makedirs(candidate_out_dir, exist_ok=True)
                            local_path = os.path.join(candidate_out_dir, filename)
                            with open(local_path, "w", encoding="utf-8") as file_handle:
                                json.dump(data, file_handle, ensure_ascii=False, indent=2)
                            print(f"Wrote {blob_name} -> {local_path}")

                        # Also write matching home JSON(s) into direct/
                        home_records = [
                            r for r in direct_home_records
                            if candidate_id_str in os.path.basename(str(r.get("blob") or ""))
                        ]
                        if home_records:
                            direct_out_dir = os.path.join(write_dir, country_lower, platform_lower, "direct")
                            os.makedirs(direct_out_dir, exist_ok=True)
                            for hr in home_records:
                                blob_name = hr["blob"]
                                data = hr["data"]
                                filename = os.path.basename(blob_name)
                                local_path = os.path.join(direct_out_dir, filename)
                                with open(local_path, "w", encoding="utf-8") as file_handle:
                                    json.dump(data, file_handle, ensure_ascii=False, indent=2)
                                print(f"Wrote {blob_name} -> {local_path}")
                        continue

                    sub_metrics = compute_instagram_metrics_from_records(records)
                    own_posts_retrieved = int(sub_metrics.get("files", 0))

                    home_records = [
                        r for r in direct_home_records
                        if candidate_id_str in os.path.basename(str(r.get("blob") or ""))
                    ]
                    home_metrics = compute_instagram_home_metrics_from_records(home_records, instagram_username)

                    row = {
                        "candidate": candidate_id_str,
                        "candidate_name": candidate_name,
                        "instagram_username": instagram_username,
                        "own_posts_raw": home_metrics.get("own_posts_raw", 0),
                        "own_posts": home_metrics.get("own_posts", 0),
                        "own_posts_retrieved": own_posts_retrieved,
                        "items": sub_metrics.get("items", 0),
                        "unique_users": sub_metrics.get("unique_users", 0),
                        "sum_child_comment_count": sub_metrics.get("sum_child_comment_count", 0),
                        "sum_comment_like_count": sub_metrics.get("sum_comment_like_count", 0),
                        "sum_post_like_count": home_metrics.get("sum_post_like_count", 0),
                        "sum_post_comment_count": home_metrics.get("sum_post_comment_count", 0),
                    }
                    rows.append(row)

                rows_sorted = sorted(rows, key=lambda r: order_index.get(r.get("candidate"), 10**9))
                print_metrics_table_custom(
                    f"INSTAGRAM CANDIDATE SUMMARY ({country_lower} / instagram)",
                    rows_sorted,
                    ig_columns,
                )

                if args.out_csv:
                    out_base = str(args.out_csv)
                    if out_base.endswith(".csv"):
                        out_base = os.path.dirname(out_base) or "."
                    paths = _build_reports_paths(out_base, country_lower, platform_lower)
                    write_csv(paths["report_instagram"], rows_sorted, ig_columns)
                    print(f"Wrote CSV: {paths['report_instagram']}")

                return 0
            # --- YouTube candidate summary ---
            if platform_lower == "youtube":
                if not (cfg and isinstance(cfg_candidates, list) and len(cfg_candidates) > 0):
                    raise RuntimeError("YouTube reporting requires YAML candidates (config/<country>.yaml)")

                yt_columns = [
                    "candidate",
                    "candidate_name",
                    "youtube_channel_id",
                    "videos",
                    "videos_own",
                    "own_posts_retrieved",
                    "unique_channels",
                    "sum_view_count",
                    "sum_like_count",
                    "sum_comment_count",
                    "avg_duration_seconds",
                    "languages",
                ]

                rows: List[Dict[str, Any]] = []
                for c in cfg_candidates:
                    if not isinstance(c, dict):
                        continue
                    candidate_id_str = str(c.get("candidate_id") or "").strip()
                    if not candidate_id_str:
                        continue
                    candidate_name = str(c.get("name") or "").strip()
                    youtube_channel_id = str(c.get("youtube_channel_id") or "").strip()

                    prefix = f"raw/{args.country}/{args.platform}/{candidate_id_str}"
                    records = read_json_folder(args.bucket, prefix)

                    if write_dir:
                        for record in records:
                            blob_name = record["blob"]
                            data = record["data"]
                            filename = os.path.basename(blob_name)
                            candidate_out_dir = os.path.join(write_dir, country_lower, platform_lower, candidate_id_str)
                            os.makedirs(candidate_out_dir, exist_ok=True)
                            local_path = os.path.join(candidate_out_dir, filename)
                            with open(local_path, "w", encoding="utf-8") as file_handle:
                                json.dump(data, file_handle, ensure_ascii=False, indent=2)
                            print(f"Wrote {blob_name} -> {local_path}")
                        continue

                    m = compute_youtube_metrics_from_records(records, youtube_channel_id)

                    row = {
                        "candidate": candidate_id_str,
                        "candidate_name": candidate_name,
                        "youtube_channel_id": youtube_channel_id,
                        "videos": m.get("videos", 0),
                        "videos_own": m.get("videos_own", 0),
                        # Keep naming consistent with other reports: files retrieved from candidate folder
                        "own_posts_retrieved": m.get("files", 0),
                        "unique_channels": m.get("unique_channels", 0),
                        "sum_view_count": m.get("sum_view_count", 0),
                        "sum_like_count": m.get("sum_like_count", 0),
                        "sum_comment_count": m.get("sum_comment_count", 0),
                        "avg_duration_seconds": m.get("avg_duration_seconds", 0),
                        "languages": m.get("languages", ""),
                    }
                    rows.append(row)

                rows_sorted = sorted(rows, key=lambda r: order_index.get(r.get("candidate"), 10**9))
                print_metrics_table_custom(
                    f"YOUTUBE CANDIDATE SUMMARY ({country_lower} / youtube)",
                    rows_sorted,
                    yt_columns,
                )

                if args.out_csv:
                    out_base = str(args.out_csv)
                    if out_base.endswith(".csv"):
                        out_base = os.path.dirname(out_base) or "."
                    paths = _build_reports_paths(out_base, country_lower, platform_lower)
                    write_csv(paths["report_youtube"], rows_sorted, yt_columns)
                    print(f"Wrote CSV: {paths['report_youtube']}")

                return 0

            if cfg and isinstance(cfg_candidates, list) and len(cfg_candidates) > 0:
                total_summary = {
                    "files": 0,
                    "items": 0,
                    "tweets": 0,
                    "replies": 0,
                    "retweets": 0,
                    "quotes": 0,
                    "media_items": 0,
                    "sum_reply_count": 0,
                    "sum_retweet_count": 0,
                    "sum_quote_count": 0,
                    "sum_favorite_count": 0,
                }

                # Direct (home) JSONs under raw/<country>/<platform>/ (e.g., own posts)
                base_prefix = f"raw/{args.country}/{args.platform}/"
                direct_home_records = read_json_files_directly_under_prefix(args.bucket, base_prefix)

                rows = []
                for c in cfg_candidates:
                    if not isinstance(c, dict):
                        continue
                    candidate_id_str = str(c.get("candidate_id") or "").strip()
                    if not candidate_id_str:
                        continue
                    candidate_name = str(c.get("name") or "").strip()
                    twitter_username = str(c.get("twitter_username") or "").strip()

                    prefix = f"raw/{args.country}/{args.platform}/{candidate_id_str}"
                    records = read_json_folder(args.bucket, prefix)

                    if write_dir:
                        for record in records:
                            blob_name = record["blob"]
                            data = record["data"]
                            filename = os.path.basename(blob_name)
                            candidate_out_dir = os.path.join(write_dir, country_lower, platform_lower, candidate_id_str)
                            os.makedirs(candidate_out_dir, exist_ok=True)
                            local_path = os.path.join(candidate_out_dir, filename)
                            with open(local_path, "w", encoding="utf-8") as file_handle:
                                json.dump(data, file_handle, ensure_ascii=False, indent=2)
                            print(f"Wrote {blob_name} -> {local_path}")
                        # Also write matching home JSON(s) (direct files) into a direct/ folder
                        home_records = [
                            r for r in direct_home_records
                            if candidate_id_str in os.path.basename(str(r.get("blob") or ""))
                        ]
                        if home_records:
                            direct_out_dir = os.path.join(write_dir, country_lower, platform_lower, "direct")
                            os.makedirs(direct_out_dir, exist_ok=True)
                            for hr in home_records:
                                blob_name = hr["blob"]
                                data = hr["data"]
                                filename = os.path.basename(blob_name)
                                local_path = os.path.join(direct_out_dir, filename)
                                with open(local_path, "w", encoding="utf-8") as file_handle:
                                    json.dump(data, file_handle, ensure_ascii=False, indent=2)
                                print(f"Wrote {blob_name} -> {local_path}")
                    else:
                        summary = compute_metrics_from_records(records)

                        # Home items: sum items from direct JSON(s) whose filename contains this candidate_id
                        home_records = [
                            r for r in direct_home_records
                            if candidate_id_str in os.path.basename(str(r.get("blob") or ""))
                        ]
                        own_posts_raw = compute_metrics_from_records(home_records).get("items", 0) if home_records else 0
                        own_posts = _count_items_by_username(home_records, twitter_username) if home_records else 0

                        own_posts_retrieved = summary.get("files", 0)
                        summary_no_files = dict(summary)
                        summary_no_files.pop("files", None)

                        row = {
                            "candidate": candidate_id_str,
                            "candidate_name": candidate_name,
                            "twitter_username": twitter_username,
                            "own_posts_raw": own_posts_raw,
                            "own_posts": own_posts,
                            "own_posts_retrieved": own_posts_retrieved,
                        }
                        row.update(summary_no_files)
                        rows.append(row)
                        for k in total_summary:
                            total_summary[k] += summary.get(k, 0)

                # After all candidates processed, print exactly one summary table for Twitter (YAML mode)
                if not write_dir:
                    rows_sorted = sorted(rows, key=lambda r: order_index.get(r.get("candidate"), 10**9))
                    print_metrics_table(f"CANDIDATE SUMMARY ({country_lower} / twitter)", rows_sorted)
                    # CSV output if requested
                    if args.out_csv:
                        out_base = str(args.out_csv)
                        if out_base.endswith(".csv"):
                            out_base = os.path.dirname(out_base) or "."
                        paths = _build_reports_paths(out_base, country_lower, platform_lower)
                        cols = [
                            "candidate","candidate_name","twitter_username",
                            "own_posts_raw","own_posts","own_posts_retrieved",
                            "items","tweets","replies","retweets","quotes","media_items",
                            "sum_reply_count","sum_retweet_count","sum_quote_count","sum_favorite_count",
                        ]
                        write_csv(paths["report2"], rows_sorted, cols)
                        print(f"Wrote CSV: {paths['report2']}")

            elif cfg is None:
                # Fallback: use Google Sheet tab
                df = read_google_sheet(
                    spreadsheet_id=args.spreadsheet_id,
                    sheet_name=sheet_tab,
                    google_creds_json=args.google_creds_json,
                )
                id_col = _pick_id_column(df)
                if id_col:
                    total_summary = {
                        "files": 0,
                        "items": 0,
                        "tweets": 0,
                        "replies": 0,
                        "retweets": 0,
                        "quotes": 0,
                        "media_items": 0,
                        "sum_reply_count": 0,
                        "sum_retweet_count": 0,
                        "sum_quote_count": 0,
                        "sum_favorite_count": 0,
                    }
                    base_prefix = f"raw/{args.country}/{args.platform}/"
                    direct_home_records = read_json_files_directly_under_prefix(args.bucket, base_prefix)
                    rows = []
                    for candidate_id in df[id_col].dropna().unique():
                        candidate_id_str = str(candidate_id).strip()
                        if not candidate_id_str:
                            continue
                        prefix = f"raw/{args.country}/{args.platform}/{candidate_id_str}"
                        records = read_json_folder(args.bucket, prefix)
                        if write_dir:
                            for record in records:
                                blob_name = record["blob"]
                                data = record["data"]
                                filename = os.path.basename(blob_name)
                                candidate_out_dir = os.path.join(write_dir, country_lower, platform_lower, candidate_id_str)
                                os.makedirs(candidate_out_dir, exist_ok=True)
                                local_path = os.path.join(candidate_out_dir, filename)
                                with open(local_path, "w", encoding="utf-8") as file_handle:
                                    json.dump(data, file_handle, ensure_ascii=False, indent=2)
                                print(f"Wrote {blob_name} -> {local_path}")
                        else:
                            summary = compute_metrics_from_records(records)

                            home_records = [
                                r for r in direct_home_records
                                if candidate_id_str in os.path.basename(str(r.get("blob") or ""))
                            ]
                            home_items = compute_metrics_from_records(home_records).get("items", 0) if home_records else 0

                            own_posts_raw = home_items
                            own_posts = 0
                            own_posts_retrieved = summary.get("files", 0)
                            summary_no_files = dict(summary)
                            summary_no_files.pop("files", None)
                            row = {
                                "candidate": candidate_id_str,
                                "candidate_name": name_map.get(candidate_id_str, ""),
                                "twitter_username": "",
                                "own_posts_raw": own_posts_raw,
                                "own_posts": own_posts,
                                "own_posts_retrieved": own_posts_retrieved,
                            }
                            row.update(summary_no_files)
                            rows.append(row)
                            for k in total_summary:
                                total_summary[k] += summary.get(k, 0)

                    if not write_dir:
                        rows_sorted = sorted(rows, key=lambda r: r["items"], reverse=True)
                        print_metrics_table(f"CANDIDATE SUMMARY ({country_lower} / {platform_lower})", rows_sorted)
                        if args.out_csv:
                            out_base = str(args.out_csv)
                            if out_base.endswith(".csv"):
                                out_base = os.path.dirname(out_base) or "."
                            paths = _build_reports_paths(out_base, country_lower, platform_lower)
                            cols = [
                                "candidate","candidate_name","twitter_username",
                                "own_posts_raw","own_posts","own_posts_retrieved",
                                "items","tweets","replies","retweets","quotes","media_items",
                                "sum_reply_count","sum_retweet_count","sum_quote_count","sum_favorite_count",
                            ]
                            write_csv(paths["report2"], rows_sorted, cols)
                            print(f"Wrote CSV: {paths['report2']}")
                else:
                    prefix = f"raw/{args.country}/{args.platform}/"
                    records = read_json_folder(args.bucket, prefix)
                    if write_dir:
                        for record in records:
                            blob_name = record["blob"]
                            data = record["data"]
                            filename = os.path.basename(blob_name)
                            out_dir = os.path.join(write_dir, country_lower, platform_lower)
                            os.makedirs(out_dir, exist_ok=True)
                            local_path = os.path.join(out_dir, filename)
                            with open(local_path, "w", encoding="utf-8") as file_handle:
                                json.dump(data, file_handle, ensure_ascii=False, indent=2)
                            print(f"Wrote {blob_name} -> {local_path}")
                    else:
                        summary = compute_metrics_from_records(records)
                        row = {"candidate": prefix, "candidate_name": ""}
                        row.update(summary)
                        print_metrics_table("DATASET SUMMARY", [row])
        else:
            prefix_norm = _normalize_prefix(args.prefix)
            parts = [p for p in prefix_norm.split("/") if p]
            cfg = None
            name_map = {}
            country_from_prefix = None
            if len(parts) >= 2 and parts[0] == "raw":
                country_from_prefix = parts[1]
                cfg = _try_load_country_config(country_from_prefix, args.config_dir)
                name_map = _candidate_name_map_from_config(cfg)

            # Compute country/platform for foldering (YAML is ground truth if present)
            country_lower = _resolve_country_lower(country_from_prefix, cfg)
            platform_lower = _resolve_platform_lower(None, parts)

            is_base_prefix = (len(parts) == 3 and parts[0] == "raw") or args.prefix.endswith("/")

            if is_base_prefix:
                # Report 1: direct files as candidates
                direct_records = read_json_files_directly_under_prefix(args.bucket, args.prefix)
                direct_candidates = {}
                for record in direct_records:
                    candidate = Path(record["blob"]).stem
                    direct_candidates.setdefault(candidate, []).append(record)

                # Report 2: subfolder grouped candidates
                grouped_records = read_json_by_candidate_folder(args.bucket, args.prefix)
                # If YAML config exists, restrict to candidate_ids defined in YAML (ground truth)
                if cfg and isinstance(cfg.get("candidates"), list):
                    yaml_ids = [str(c.get("candidate_id")).strip() for c in cfg.get("candidates") if isinstance(c, dict) and c.get("candidate_id")]
                    grouped_records = {cid: grouped_records.get(cid, []) for cid in yaml_ids}

                if write_dir:
                    # Write all JSON files (direct + subfolder)
                    for record in direct_records:
                        blob_name = record["blob"]
                        data = record["data"]
                        filename = os.path.basename(blob_name)
                        out_dir = os.path.join(write_dir, country_lower, platform_lower, "direct")
                        os.makedirs(out_dir, exist_ok=True)
                        local_path = os.path.join(out_dir, filename)
                        with open(local_path, "w", encoding="utf-8") as file_handle:
                            json.dump(data, file_handle, ensure_ascii=False, indent=2)
                        print(f"Wrote {blob_name} -> {local_path}")
                    for candidate_id in grouped_records.keys():
                        for record in grouped_records.get(candidate_id, []):
                            blob_name = record["blob"]
                            data = record["data"]
                            filename = os.path.basename(blob_name)
                            out_dir = os.path.join(write_dir, country_lower, platform_lower, str(candidate_id))
                            os.makedirs(out_dir, exist_ok=True)
                            local_path = os.path.join(out_dir, filename)
                            with open(local_path, "w", encoding="utf-8") as file_handle:
                                json.dump(data, file_handle, ensure_ascii=False, indent=2)
                            print(f"Wrote {blob_name} -> {local_path}")
                else:
                    # Report 1
                    rows_report1 = []
                    for candidate, records in direct_candidates.items():
                        summary = compute_metrics_from_records(records)
                        first_blob = records[0]["blob"] if records else ""
                        own_posts_raw = summary.get("items", 0)
                        own_posts = 0
                        own_posts_retrieved = summary.get("files", 0)
                        summary_no_files = dict(summary)
                        summary_no_files.pop("files", None)
                        row = {
                            "candidate": candidate,
                            "candidate_name": "",
                            "twitter_username": "",
                            "own_posts_raw": own_posts_raw,
                            "own_posts": own_posts,
                            "own_posts_retrieved": own_posts_retrieved,
                            "source": os.path.basename(first_blob),
                            "example_tweet_url": pick_example_tweet_url(records),
                            "description_short": dominant_description_short(records),
                        }
                        row.update(summary_no_files)
                        rows_report1.append(row)
                    rows_report1_sorted = sorted(rows_report1, key=lambda r: r["items"], reverse=True)
                    print_metrics_table("REPORT 1: Direct files (own posts)", rows_report1_sorted)
                    # Description breakdown: print for candidates with >1 unique description
                    for row in rows_report1_sorted:
                        candidate = row["candidate"]
                        records = direct_candidates.get(candidate, [])
                        desc_counts = count_items_by_description(records)
                        if len(desc_counts) > 1:
                            print_description_breakdown(candidate, desc_counts)

                    # Report 2
                    rows_report2 = []
                    for candidate_id in grouped_records.keys():
                        records = grouped_records.get(candidate_id, [])
                        summary = compute_metrics_from_records(records)
                        own_posts_raw = 0
                        own_posts = 0
                        own_posts_retrieved = summary.get("files", 0)
                        summary_no_files = dict(summary)
                        summary_no_files.pop("files", None)
                        row = {
                            "candidate": candidate_id,
                            "candidate_name": name_map.get(candidate_id, ""),
                            "twitter_username": "",
                            "own_posts_raw": own_posts_raw,
                            "own_posts": own_posts,
                            "own_posts_retrieved": own_posts_retrieved,
                            "source": candidate_id,
                            "example_tweet_url": pick_example_tweet_url(records),
                            "description_short": dominant_description_short(records),
                        }
                        row.update(summary_no_files)
                        rows_report2.append(row)
                    rows_report2_sorted = sorted(rows_report2, key=lambda r: r["items"], reverse=True)
                    print_metrics_table("REPORT 2: Subfolders (posts + replies)", rows_report2_sorted)
                    if args.out_csv:
                        columns = [
                            "candidate","candidate_name","twitter_username",
                            "own_posts_raw","own_posts","own_posts_retrieved",
                            "items","tweets","replies","retweets","quotes","media_items",
                            "sum_reply_count","sum_retweet_count","sum_quote_count","sum_favorite_count",
                        ]
                        user_columns = [
                            "source",
                            "right_user",
                            "user_id_str",
                            "screen_name",
                            "name",
                            "lang",
                            "description_short",
                            "example_tweet_url",
                            "files",
                            "items",
                            "tweets",
                            "replies",
                            "retweets",
                            "quotes",
                            "media_items",
                            "sum_reply_count",
                        ]
                        out_base = str(args.out_csv)
                        if out_base.endswith(".csv"):
                            out_base = os.path.dirname(out_base) or "."
                        # Use helpers to get output paths
                        paths = _build_reports_paths(out_base, country_lower, platform_lower)
                        out1 = paths["report1"]
                        out2 = paths["report2"]
                        out1u = paths["report1_users"]
                        write_csv(out1, rows_report1_sorted, columns)
                        write_csv(out2, rows_report2_sorted, columns)
                        print(f"Wrote CSV: {out1}")
                        print(f"Wrote CSV: {out2}")

                        # Per-candidate one-row summaries from report2
                        # (Disabled: do not create one-line per-candidate CSVs.)

                        # Build user breakdown CSV
                        user_rows1 = []
                        for row in rows_report1_sorted:
                            candidate = row["candidate"]
                            records = direct_candidates.get(candidate, [])
                            urows = compute_user_breakdown(records, candidate=candidate, source=row.get("source", ""))
                            for ur in urows:
                                ur["right_user"] = ""
                                user_rows1.append(ur)
                        write_csv(out1u, user_rows1, user_columns)
                        print(f"Wrote CSV: {out1u}")
            else:
                records = read_json_folder(args.bucket, args.prefix)
                if not records:
                    print("No JSON files found.")
                    return 0

                print(f"Found {len(records)} JSON files in gs://{args.bucket}/{_normalize_prefix(args.prefix)}")

                if write_dir:
                    for record in records:
                        blob_name = record["blob"]
                        data = record["data"]
                        filename = os.path.basename(blob_name)
                        out_dir = os.path.join(write_dir, country_lower, platform_lower)
                        os.makedirs(out_dir, exist_ok=True)
                        local_path = os.path.join(out_dir, filename)
                        with open(local_path, "w", encoding="utf-8") as file_handle:
                            json.dump(data, file_handle, ensure_ascii=False, indent=2)
                        print(f"Wrote {blob_name} -> {local_path}")
                else:
                    summary = compute_metrics_from_records(records)
                    first_blob = records[0]["blob"] if records else ""
                    row = {
                        "candidate": args.prefix,
                        "candidate_name": "",
                        "source": os.path.basename(first_blob),
                        "example_tweet_url": pick_example_tweet_url(records),
                        "description_short": dominant_description_short(records),
                    }
                    row.update(summary)
                    print_metrics_table("DATASET SUMMARY", [row])

    except Exception as exc:  # noqa: BLE001
        print(f"Error reading JSON from GCS: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
