#!/usr/bin/env python3
"""
Script to upload records from CSV to Google Cloud Firestore.

Uploads records with indexed fields:
- platform
- country
- candidate_id
- created_at
- status (default: "noreplies")

Non-indexed fields:
- replies_count
- max_replies

The script reads GCP_PROJECT_ID from .env file (or command line argument).
Create a .env file in the project root with:
    GCP_PROJECT_ID=your-project-id

IMPORTANT:
- Before running queries, create composite indexes in Firestore console or using gcloud commands if needed for complex queries.
- To exclude replies_count and max_replies from indexes, configure single-field index exemptions in the Firestore console.

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

    records_uploaded = 0

    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for i, row in enumerate(reader):
            # Skip records before the starting position
            if i < skip:
                continue

            # Stop after uploading the requested number of records (if limit is set)
            if limit is not None and records_uploaded >= limit:
                break

            # Extract fields from CSV
            platform = row.get("platform", "")
            post_id = row.get("post_id", "")
            replies_count = row.get("replies_count", "")
            country = row.get("country", "")
            candidate_id = row.get("candidate_id", "")
            max_replies = row.get("max_replies", "")
            created_at = row.get("created_at", "")
            status = "noreplies"  # Default value

            # Prepare document data
            doc_data = {
                # Indexed fields
                "platform": platform,
                "post_id": post_id,
                "country": country,
                "candidate_id": candidate_id,
                "created_at": created_at,
                "status": status,
            }

            # Add non-indexed fields
            # Note: To exclude these from indexes, configure single-field index exemptions
            # in the Firestore console or via gcloud commands
            if replies_count:
                try:
                    doc_data["replies_count"] = int(replies_count)
                except (ValueError, TypeError):
                    doc_data["replies_count"] = replies_count
            if max_replies:
                try:
                    doc_data["max_replies"] = int(max_replies)
                except (ValueError, TypeError):
                    doc_data["max_replies"] = max_replies

            # Create a new document with auto-generated ID
            doc_ref = client.collection(collection).document()
            doc_ref.set(doc_data)
            records_uploaded += 1

            print(
                f"Uploaded record {i + 1} (position {i + 1} in CSV): platform={platform}, "
                f"country={country}, candidate_id={candidate_id}, created_at={created_at}"
            )

    print(
        f"\nSuccessfully uploaded {records_uploaded} records to Firestore database '{database_name}'"
    )
    if skip > 0:
        print(f"Skipped first {skip} records from CSV")
    if limit is not None and records_uploaded < limit:
        print(
            f"Warning: Only {records_uploaded} records were uploaded (requested {limit}). "
            f"CSV file may have fewer records than expected."
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
    print(f"Project ID: {project_id or 'default from gcloud'}\n")

    upload_to_firestore(
        args.csv_path,
        args.collection,
        args.database_name,
        project_id,
        limit,
        args.skip,
    )
