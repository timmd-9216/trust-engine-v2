#!/usr/bin/env python3
"""
Transform JSON post/reply files to CSV (same columns as ownposts_venezuela_partial.csv + start_date, end_date).

Supports:
- Twitter format: {"data": [{id_str, created_at, reply_count, ...}]}
- Instagram comments: {"data": [{pk, original_post_pk, created_at, ...}]} (aggregates by original_post_pk)

Output columns: platform, post_id, country, candidate_id, username, created_at,
replies_count, error_query, max_posts_replies, sort_by, start_date, end_date

Usage:
  poetry run python scripts/json_posts_to_csv.py data/file1.json -o out.csv --country XX --candidate-id YY
"""

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path


def detect_format(data: list) -> str:
    """Return 'twitter' or 'instagram' based on first element keys."""
    if not data:
        raise ValueError("JSON 'data' array is empty")
    first = data[0]
    if isinstance(first, dict):
        if "id_str" in first and "reply_count" in first:
            return "twitter"
        if "original_post_pk" in first and "pk" in first:
            return "instagram"
    raise ValueError(
        "Unknown format: first element must have (id_str, reply_count) for Twitter "
        "or (original_post_pk, pk) for Instagram"
    )


def parse_twitter_created_at(s: str) -> str:
    """Parse 'Mon Oct 20 22:39:58 +0000 2025' to ISO string."""
    if not s:
        return ""
    try:
        dt = parsedate_to_datetime(s)
        return dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    except (ValueError, TypeError):
        return s


def rows_from_twitter(
    data: list,
    *,
    platform: str,
    country: str,
    candidate_id: str,
    start_date: str,
    end_date: str,
    error_query: str = "false",
    sort_by: str = "engagement",
) -> list[dict]:
    """Build CSV rows from Twitter-style data array."""
    rows = []
    for item in data:
        if not isinstance(item, dict):
            continue
        post_id = item.get("id_str") or ""
        if not post_id:
            continue
        created_at = parse_twitter_created_at(item.get("created_at") or "")
        reply_count = item.get("reply_count")
        if reply_count is None:
            reply_count = 0
        try:
            reply_count = int(reply_count)
        except (TypeError, ValueError):
            reply_count = 0
        rows.append(
            {
                "platform": platform,
                "post_id": post_id,
                "country": country,
                "candidate_id": candidate_id,
                "username": item.get("screen_name") or "",
                "created_at": created_at,
                "replies_count": str(reply_count),
                "error_query": error_query,
                "max_posts_replies": str(reply_count),
                "sort_by": sort_by,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
    return rows


def rows_from_instagram(
    data: list,
    *,
    platform: str,
    country: str,
    candidate_id: str,
    start_date: str,
    end_date: str,
    error_query: str = "false",
    sort_by: str = "time",
) -> list[dict]:
    """Aggregate Instagram comments by original_post_pk; one row per post."""
    from collections import defaultdict

    groups: dict[str, list[dict]] = defaultdict(list)
    for item in data:
        if not isinstance(item, dict):
            continue
        post_pk = item.get("original_post_pk")
        if not post_pk:
            continue
        groups[post_pk].append(item)

    rows = []
    for post_id, comments in groups.items():
        count = len(comments)
        created_at = ""
        min_ts = None
        for c in comments:
            ts = c.get("created_at")
            if ts is not None:
                try:
                    t = int(ts)
                    if min_ts is None or t < min_ts:
                        min_ts = t
                except (TypeError, ValueError):
                    pass
        if min_ts is not None:
            try:
                dt = datetime.fromtimestamp(min_ts, tz=timezone.utc)
                created_at = dt.strftime("%Y-%m-%dT%H:%M:%S%z")
            except (ValueError, OSError):
                pass
        username = (comments[0].get("username") or "") if comments else ""
        rows.append(
            {
                "platform": platform,
                "post_id": post_id,
                "country": country,
                "candidate_id": candidate_id,
                "username": username,
                "created_at": created_at,
                "replies_count": str(count),
                "error_query": error_query,
                "max_posts_replies": str(count),
                "sort_by": sort_by,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
    return rows


# Same columns as ownposts_venezuela_partial.csv + max_posts_replies (required for upload) + start_date, end_date
CSV_COLUMNS = [
    "platform",
    "post_id",
    "country",
    "candidate_id",
    "username",
    "created_at",
    "replies_count",
    "error_query",
    "max_posts_replies",
    "sort_by",
    "start_date",
    "end_date",
]


def load_json(path: Path) -> list:
    """Load JSON file and return the 'data' array."""
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, dict) or "data" not in obj:
        raise ValueError(f"{path}: expected object with 'data' array")
    data = obj["data"]
    if not isinstance(data, list):
        raise ValueError(f"{path}: 'data' must be a list")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert JSON post/reply files to CSV for Firestore upload",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help='Paths to JSON files (each with {"data": [...]})',
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="Output CSV path",
    )
    parser.add_argument(
        "--country",
        type=str,
        required=True,
        help="Country code for all rows (not present in JSON)",
    )
    parser.add_argument(
        "--candidate-id",
        type=str,
        required=True,
        dest="candidate_id",
        help="Candidate ID for all rows (not present in JSON)",
    )
    parser.add_argument(
        "--platform",
        type=str,
        choices=("twitter", "instagram"),
        default=None,
        help="Override platform (default: inferred per file from content)",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default="2025-10-12",
        help="start_date value for all rows (default: 2025-10-12)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default="2025-10-28",
        help="end_date value for all rows (default: 2025-10-28)",
    )
    parser.add_argument(
        "--error-query",
        type=str,
        default="false",
        help="error_query value for all rows (default: false)",
    )
    parser.add_argument(
        "--sort-by",
        type=str,
        default=None,
        help="sort_by value (default: engagement for Twitter, time for Instagram)",
    )
    args = parser.parse_args()

    all_rows: list[dict] = []
    for path in args.inputs:
        if not path.exists():
            print(f"Error: file not found: {path}", file=sys.stderr)
            return 1
        try:
            data = load_json(path)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"Error reading {path}: {e}", file=sys.stderr)
            return 1
        fmt = detect_format(data)
        platform = args.platform or fmt
        if args.platform and args.platform != fmt:
            print(
                f"Warning: --platform={args.platform} overrides detected format '{fmt}' for {path}",
                file=sys.stderr,
            )
        sort_by = args.sort_by or ("engagement" if fmt == "twitter" else "time")
        if fmt == "twitter":
            rows = rows_from_twitter(
                data,
                platform=platform,
                country=args.country,
                candidate_id=args.candidate_id,
                start_date=args.start_date,
                end_date=args.end_date,
                error_query=args.error_query,
                sort_by=sort_by,
            )
        else:
            rows = rows_from_instagram(
                data,
                platform=platform,
                country=args.country,
                candidate_id=args.candidate_id,
                start_date=args.start_date,
                end_date=args.end_date,
                error_query=args.error_query,
                sort_by=sort_by,
            )
        all_rows.extend(rows)
        print(f"{path.name}: detected {fmt}, produced {len(rows)} rows", file=sys.stderr)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\nWrote {len(all_rows)} rows to {args.output}", file=sys.stderr)
    print("\n--- CSV preview (first 15 lines) ---", file=sys.stderr)
    with open(args.output, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= 16:
                break
            print(line.rstrip())
    if len(all_rows) > 15:
        print("...", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
