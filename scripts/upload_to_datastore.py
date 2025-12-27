#!/usr/bin/env python3
"""
Script to upload first 10 records from CSV to Google Cloud Firestore.

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

Example: python upload_to_firestore.py <csv_path> <collection> [database_name] [project_id] [limit]
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
    limit: int = 10,
):
    """
    Upload first N records from CSV to Firestore.

    Args:
        csv_path: Path to the CSV file
        collection: Firestore collection name
        database_name: Firestore database name
        project_id: GCP project ID (if None, uses default from gcloud)
        limit: Number of records to upload (default: 10)
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
            if i >= limit:
                break

            # Extract fields from CSV
            platform = row.get("platform", "")
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
                f"Uploaded record {i + 1}: platform={platform}, "
                f"country={country}, candidate_id={candidate_id}, created_at={created_at}"
            )

    print(
        f"\nSuccessfully uploaded {records_uploaded} records to Firestore database '{database_name}'"
    )
    return records_uploaded


if __name__ == "__main__":
    # Get CSV path from command line or use default
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
    else:
        # Default to the data file in the project
        project_root = Path(__file__).parent.parent
        csv_path = project_root / "data" / "account_search-hnd01_rive.csv"

    # Get collection from command line (required)
    if len(sys.argv) > 2:
        collection = sys.argv[2]
    else:
        print("Error: 'collection' parameter is required")
        print(
            "Usage: python upload_to_firestore.py <csv_path> <collection> [database_name] [project_id] [limit]"
        )
        sys.exit(1)

    # Get database name from command line or use default
    if len(sys.argv) > 3:
        database_name = sys.argv[3]
    else:
        database_name = "socialnetworks"  # Default

    # Get project ID from .env file (loaded via load_dotenv())
    project_id = os.getenv("GCP_PROJECT_ID")

    # Get limit from command line or use default
    limit = 10

    # Parse remaining arguments: project_id and limit
    if len(sys.argv) > 4:
        # Check if arg4 is a number (limit) or text (project_id)
        arg4 = sys.argv[4]
        try:
            limit = int(arg4)
            # It's a number, so it's the limit, project_id stays from .env
        except ValueError:
            # It's not a number, so it's the project_id
            project_id = arg4
            # Check if there's a limit as arg5
            if len(sys.argv) > 5:
                try:
                    limit = int(sys.argv[5])
                except ValueError:
                    print("Warning: Invalid limit value, using default of 10")

    print(f"Uploading first {limit} records from {csv_path} to Firestore...")
    print(f"Collection: {collection}")
    print(f"Database: {database_name}")
    print(f"Project ID: {project_id or 'default from gcloud'}\n")

    upload_to_firestore(str(csv_path), collection, database_name, project_id, limit)
