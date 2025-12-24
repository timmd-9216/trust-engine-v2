#!/usr/bin/env python3
"""
Script to upload first 10 records from CSV to Google Cloud Datastore.

Uploads records to the "socialnetworks" database with indexed fields:
- platform
- conversation_id_str
- created_at
- status (default: "scrapped")

The script reads GCP_PROJECT_ID from .env file (or command line argument).
Create a .env file in the project root with:
    GCP_PROJECT_ID=your-project-id

IMPORTANT: Before running queries, deploy the composite indexes defined in
index.yaml using:
    gcloud datastore indexes create index.yaml --database=socialnetworks
"""

import csv
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    from google.cloud import datastore
except ImportError as e:
    missing = "dotenv" if "dotenv" in str(e) else "google-cloud-datastore"
    if missing == "dotenv":
        print("Error: python-dotenv is not installed.")
        print("Install it with: poetry add python-dotenv")
    else:
        print("Error: google-cloud-datastore is not installed.")
        print("Install it with: poetry add google-cloud-datastore")
    sys.exit(1)

# Load environment variables from .env file
load_dotenv()


def upload_to_datastore(csv_path: str, project_id: str = None, limit: int = 10):
    """
    Upload first N records from CSV to Datastore.

    Args:
        csv_path: Path to the CSV file
        project_id: GCP project ID (if None, uses default from gcloud)
        limit: Number of records to upload (default: 10)
    """
    # Initialize Datastore client
    if project_id:
        client = datastore.Client(project=project_id, database="socialnetworks")
    else:
        client = datastore.Client(database="socialnetworks")

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

            # Extract only the fields we want to index
            platform = row.get("platform", "")
            conversation_id_str = row.get("conversation_id_str", "")
            created_at = row.get("created_at", "")
            status = "scrapped"  # Default value

            # Create a new entity
            # Using conversation_id_str as the key if available, otherwise generate one
            if conversation_id_str:
                key = client.key("social_post", conversation_id_str)
            else:
                key = client.key("social_post")

            entity = datastore.Entity(key=key)

            # Set only the indexed fields
            entity["platform"] = platform
            entity["conversation_id_str"] = conversation_id_str
            entity["created_at"] = created_at
            entity["status"] = status

            # Save the entity
            client.put(entity)
            records_uploaded += 1

            print(
                f"Uploaded record {i + 1}: platform={platform}, "
                f"conversation_id={conversation_id_str}, created_at={created_at}"
            )

    print(
        f"\nSuccessfully uploaded {records_uploaded} records to Datastore database 'socialnetworks'"
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

    # Get project ID from .env file (loaded via load_dotenv()) or command line
    # Command line argument takes precedence over .env file
    project_id = os.getenv("GCP_PROJECT_ID")
    if len(sys.argv) > 2:
        project_id = sys.argv[2]

    # Get limit from command line or use default
    limit = 10
    if len(sys.argv) > 3:
        try:
            limit = int(sys.argv[3])
        except ValueError:
            print("Warning: Invalid limit value, using default of 10")

    print(f"Uploading first {limit} records from {csv_path} to Datastore...")
    print("Database: socialnetworks")
    print(f"Project ID: {project_id or 'default from gcloud'}\n")

    upload_to_datastore(str(csv_path), project_id, limit)
