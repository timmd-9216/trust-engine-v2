#!/usr/bin/env python3
"""
Script to upload records from CSV to Google Cloud Firestore.

Uploads records with indexed fields:
- platform
- country
- candidate_id
- created_at (timestamp of insert into Firestore)
- status (default: "noreplies")

The CSV field 'created_at' is renamed to 'post_created_at' in Firestore (original post creation date).
A new 'created_at' field is created with the current timestamp (when the record is inserted).

Required CSV columns: platform, post_id, country, candidate_id, max_posts_replies.
All rows are validated before any upload; missing required column or empty value aborts with error.

Non-indexed fields:
- replies_count
- max_posts_replies
- start_date, end_date (optional; written if present in CSV)

The script reads GCP_PROJECT_ID from .env file (or command line argument).
Create a .env file in the project root with:
    GCP_PROJECT_ID=your-project-id

IMPORTANT:
- Before running queries, create composite indexes in Firestore console or using gcloud commands if needed for complex queries.
- To exclude replies_count and max_posts_replies from indexes, configure single-field index exemptions in the Firestore console.

Examples:
  # Upload first 50 records
  python upload_to_firestore.py <csv_path> <collection> [database_name] [project_id] [limit]

  # Upload records starting from position 50 (skip first 50)
  python upload_to_firestore.py <csv_path> <collection> [database_name] [project_id] [limit] [skip]

  # Upload next 50 records after the first 50
  python upload_to_firestore.py data/test-input.csv posts socialnetworks trust-481601 50 50
"""

import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
    from google.cloud import firestore
except ImportError as e:
    missing = "dotenv" if "dotenv" in str(e) else "google-cloud-firestore"
    if missing == "dotenv":
        print("Error: python-dotenv is not installed.")
        print("Install it with: poetry add python-dotenv")
    else:
        print("Error: google-cloud-firestore is not installed.")
        print("Install it with: poetry add google-cloud-firestore")
    sys.exit(1)

# Load environment variables from .env file
load_dotenv()


def upload_to_firestore(
    csv_path: str,
    collection: str,
    database_name: str,
    project_id: str = None,
    limit: int | None = 10,
    skip: int = 0,
    skip_existing: bool = False,
    max_posts_replies_limit: int | None = None,
):
    """
    Upload records from CSV to Firestore.

    Args:
        csv_path: Path to the CSV file
        collection: Firestore collection name
        database_name: Firestore database name
        project_id: GCP project ID (if None, uses default from gcloud)
        limit: Number of records to upload (default: 10, None to upload all)
        skip: Number of records to skip from the beginning (default: 0)
        skip_existing: If True, skip records where post_id already exists in Firestore (default: False)
        max_posts_replies_limit: Maximum value for max_posts_replies field (if None, no limit is applied)
    """
    # Initialize Firestore client
    if project_id:
        client = firestore.Client(project=project_id, database=database_name)
    else:
        client = firestore.Client(database=database_name)

    # Read CSV file
    csv_file = Path(csv_path)
    if not csv_file.exists():
        print(f"Error: CSV file not found at {csv_path}")
        sys.exit(1)

    REQUIRED_COLUMNS = ("platform", "post_id", "country", "candidate_id", "max_posts_replies")

    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        all_rows = list(reader)

    if not all_rows:
        print("Error: CSV has no data rows")
        sys.exit(1)

    # Determine rows to process (after skip, up to limit)
    end = (skip + limit) if limit is not None else None
    rows_to_process = all_rows[skip:end]

    # Validate: no missing required values in any row before processing
    for idx, row in enumerate(rows_to_process):
        row_num = skip + idx + 2  # 1-based + header line
        for col in REQUIRED_COLUMNS:
            if col not in row:
                print(f"Error: CSV row {row_num}: missing column '{col}'")
                sys.exit(1)
            val = (row.get(col) or "").strip()
            if not val:
                print(f"Error: CSV row {row_num}: missing value for required column '{col}'")
                sys.exit(1)

    records_uploaded = 0

    for idx, row in enumerate(rows_to_process):
        # Extract fields from CSV
        platform = row.get("platform", "")
        post_id = row.get("post_id", "")
        replies_count = row.get("replies_count", "")
        country = row.get("country", "")
        candidate_id = row.get("candidate_id", "")
        max_posts_replies_raw = row.get("max_posts_replies", "")
        post_created_at_str = row.get("created_at", "")
        start_date = row.get("start_date", "")
        end_date = row.get("end_date", "")
        status = "noreplies"  # Default value
        i = skip + idx

        # Convert post_created_at (from CSV) string to Firestore timestamp
        post_created_at = None
        if post_created_at_str:
            try:
                # Try to parse ISO format: "2025-12-16T09:59:35.000000" or "2025-12-16T09:59:35"
                created_at_str_clean = post_created_at_str.strip()
                if "T" in created_at_str_clean:
                    if created_at_str_clean.endswith("Z"):
                        created_at_str_clean = created_at_str_clean[:-1] + "+00:00"
                    elif "+" not in created_at_str_clean and "-" not in created_at_str_clean[-6:]:
                        created_at_str_clean = created_at_str_clean + "+00:00"
                    post_created_at = datetime.fromisoformat(created_at_str_clean)
                else:
                    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
                        try:
                            post_created_at = datetime.strptime(created_at_str_clean, fmt)
                            break
                        except ValueError:
                            continue
            except (ValueError, TypeError) as e:
                print(
                    f"Warning: Could not parse post_created_at '{post_created_at_str}' for "
                    f"post_id={post_id}: {e}"
                )
                post_created_at = post_created_at_str

        created_at = datetime.now(timezone.utc)
        doc_data = {
            "platform": platform,
            "post_id": post_id,
            "country": country,
            "candidate_id": candidate_id,
            "created_at": created_at,
            "status": status,
        }
        if post_created_at:
            doc_data["post_created_at"] = post_created_at
        if replies_count:
            try:
                doc_data["replies_count"] = int(replies_count)
            except (ValueError, TypeError):
                doc_data["replies_count"] = replies_count
        try:
            max_posts_replies_int = int(max_posts_replies_raw)
            if (
                max_posts_replies_limit is not None
                and max_posts_replies_int > max_posts_replies_limit
            ):
                max_posts_replies_int = max_posts_replies_limit
            doc_data["max_posts_replies"] = max_posts_replies_int
        except (ValueError, TypeError):
            doc_data["max_posts_replies"] = max_posts_replies_raw
        if start_date:
            doc_data["start_date"] = start_date.strip()
        if end_date:
            doc_data["end_date"] = end_date.strip()

        if skip_existing and post_id:
            existing_query = (
                client.collection(collection).where("post_id", "==", post_id).limit(1).stream()
            )
            existing_docs = list(existing_query)
            if existing_docs:
                print(
                    f"Skipped record {i + 1} (position {i + 1} in CSV): post_id={post_id} already exists"
                )
                continue

        doc_ref = client.collection(collection).document()
        doc_ref.set(doc_data)
        records_uploaded += 1
        print(
            f"Uploaded record {i + 1} (position {i + 1} in CSV): platform={platform}, "
            f"country={country}, candidate_id={candidate_id}, post_id={post_id}, created_at={created_at}"
        )

    print(
        f"\nSuccessfully uploaded {records_uploaded} records to Firestore database '{database_name}'"
    )
    if skip > 0:
        print(f"Skipped first {skip} records from CSV")
    if skip_existing:
        print("Note: Records with existing post_id were skipped (--skip-existing enabled)")
    if limit is not None and records_uploaded < limit:
        print(
            f"Warning: Only {records_uploaded} records were uploaded (requested {limit}). "
            f"CSV file may have fewer records than expected, or some were skipped due to duplicates."
        )
    return records_uploaded


if __name__ == "__main__":
    import argparse

    # Default CSV path
    project_root = Path(__file__).parent.parent
    default_csv = project_root / "data" / "account_search-hnd01_rive.csv"

    parser = argparse.ArgumentParser(
        description="Upload records from CSV to Google Cloud Firestore",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Upload first 50 records
  python upload_to_firestore.py data/test-input.csv posts socialnetworks trust-481601 50
  
  # Upload next 50 records (skip first 50)
  python upload_to_firestore.py data/test-input.csv posts socialnetworks trust-481601 50 --skip 50
  
  # Upload records 100-149 (skip 100, upload 50)
  python upload_to_firestore.py data/test-input.csv posts socialnetworks trust-481601 50 --skip 100
  
  # Upload ALL records from CSV
  python upload_to_firestore.py data/test-input.csv posts socialnetworks trust-481601 --all
  
  # Upload ALL records starting from position 50
  python upload_to_firestore.py data/test-input.csv posts socialnetworks trust-481601 --all --skip 50
  
  # Upload records skipping those that already exist (by post_id)
  python upload_to_firestore.py data/test-input.csv posts socialnetworks trust-481601 50 --skip-existing
        """,
    )
    parser.add_argument(
        "csv_path",
        type=str,
        nargs="?",
        default=str(default_csv),
        help="Path to CSV file (default: data/account_search-hnd01_rive.csv)",
    )
    parser.add_argument(
        "collection",
        type=str,
        help="Firestore collection name",
    )
    parser.add_argument(
        "database_name",
        type=str,
        nargs="?",
        default="socialnetworks",
        help="Firestore database name (default: socialnetworks)",
    )
    parser.add_argument(
        "project_id",
        type=str,
        nargs="?",
        default=None,
        help="GCP Project ID (default: from .env file or gcloud)",
    )
    parser.add_argument(
        "limit",
        type=int,
        nargs="?",
        default=10,
        help="Number of records to upload (default: 10). Can be specified as positional or with --limit",
    )
    parser.add_argument(
        "--limit",
        type=int,
        dest="limit_override",
        default=None,
        help="Number of records to upload (alternative to positional argument)",
    )
    parser.add_argument(
        "--skip",
        type=int,
        default=0,
        help="Number of records to skip from the beginning (default: 0)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Upload all records from CSV (ignores limit)",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip records where post_id already exists in Firestore",
    )
    parser.add_argument(
        "--max-posts-replies-limit",
        type=int,
        default=None,
        dest="max_posts_replies_limit",
        help="Maximum value for max_posts_replies field (if CSV value exceeds this, it will be capped)",
    )

    args = parser.parse_args()

    # Use --all flag to upload everything, otherwise use limit
    if args.all:
        limit = None
    else:
        # Use --limit if provided, otherwise use positional limit
        limit = args.limit_override if args.limit_override is not None else args.limit

    # Get project ID from args or .env file
    project_id = args.project_id or os.getenv("GCP_PROJECT_ID")

    if args.all:
        if args.skip > 0:
            print(
                f"Uploading ALL records from {args.csv_path} to Firestore "
                f"(skipping first {args.skip} records)..."
            )
        else:
            print(f"Uploading ALL records from {args.csv_path} to Firestore...")
    else:
        if args.skip > 0:
            print(
                f"Uploading {limit} records from {args.csv_path} to Firestore "
                f"(skipping first {args.skip} records)..."
            )
        else:
            print(f"Uploading first {limit} records from {args.csv_path} to Firestore...")
    print(f"Collection: {args.collection}")
    print(f"Database: {args.database_name}")
    print(f"Project ID: {project_id or 'default from gcloud'}")
    if args.skip_existing:
        print("Skip existing: Enabled (records with existing post_id will be skipped)")
    if args.max_posts_replies_limit:
        print(
            f"Max posts replies limit: {args.max_posts_replies_limit} "
            "(max_posts_replies values will be capped)"
        )
    print()

    upload_to_firestore(
        args.csv_path,
        args.collection,
        args.database_name,
        project_id,
        limit,
        args.skip,
        args.skip_existing,
        args.max_posts_replies_limit,
    )
