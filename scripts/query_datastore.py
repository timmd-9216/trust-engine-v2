#!/usr/bin/env python3
"""
Script to query Datastore for social posts with a specific status.

Queries the "socialnetworks" database for records matching the specified status
and returns their conversation_id_str values.

The script reads GCP_PROJECT_ID from .env file (or command line argument).
Create a .env file in the project root with:
    GCP_PROJECT_ID=your-project-id
"""

import os
import sys

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


def query_by_status(project_id: str = None, status: str = "scrapped", limit: int = None):
    """
    Query Datastore for records with a specific status.

    Args:
        project_id: GCP project ID (if None, uses default from gcloud)
        status: Status value to filter by (default: "scrapped")
        limit: Maximum number of results to return (None for all)

    Returns:
        List of conversation_id_str values
    """
    # Initialize Datastore client
    if project_id:
        client = datastore.Client(project=project_id, database="socialnetworks")
    else:
        client = datastore.Client(database="socialnetworks")

    # Create query
    query = client.query(kind="social_post")
    query.add_filter("status", "=", status)

    # Apply limit if specified
    if limit:
        query_iter = query.fetch(limit=limit)
    else:
        query_iter = query.fetch()

    # Extract conversation_id_str values
    conversation_ids = []
    for entity in query_iter:
        conversation_id = entity.get("conversation_id_str", "")
        if conversation_id:
            conversation_ids.append(conversation_id)

    return conversation_ids


def query_with_details(project_id: str = None, status: str = "scrapped", limit: int = None):
    """
    Query Datastore for records with a specific status and return full details.

    Args:
        project_id: GCP project ID (if None, uses default from gcloud)
        status: Status value to filter by (default: "scrapped")
        limit: Maximum number of results to return (None for all)

    Returns:
        List of dictionaries with record details
    """
    # Initialize Datastore client
    if project_id:
        client = datastore.Client(project=project_id, database="socialnetworks")
    else:
        client = datastore.Client(database="socialnetworks")

    # Create query
    query = client.query(kind="social_post")
    query.add_filter("status", "=", status)

    # Apply limit if specified
    if limit:
        query_iter = query.fetch(limit=limit)
    else:
        query_iter = query.fetch()

    # Extract full details
    records = []
    for entity in query_iter:
        record = {
            "conversation_id_str": entity.get("conversation_id_str", ""),
            "platform": entity.get("platform", ""),
            "created_at": entity.get("created_at", ""),
            "status": entity.get("status", ""),
        }
        records.append(record)

    return records


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Query Datastore for social posts by status")
    parser.add_argument(
        "--status",
        type=str,
        default="scrapped",
        help='Status to filter by (default: "scrapped")',
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of results (default: all)",
    )
    parser.add_argument(
        "--project-id",
        type=str,
        default=None,
        help="GCP Project ID (overrides .env file)",
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="Show full record details instead of just conversation_id",
    )

    args = parser.parse_args()

    # Get project ID from .env file or command line
    project_id = args.project_id or os.getenv("GCP_PROJECT_ID")

    print("Querying Datastore database 'socialnetworks'...")
    print(f"Status filter: {args.status}")
    print(f"Project ID: {project_id or 'default from gcloud'}")
    if args.limit:
        print(f"Limit: {args.limit}")
    print()

    try:
        if args.details:
            # Get full details
            records = query_with_details(project_id, args.status, args.limit)
            print(f"Found {len(records)} records:\n")
            for i, record in enumerate(records, 1):
                print(f"{i}. conversation_id: {record['conversation_id_str']}")
                print(f"   platform: {record['platform']}")
                print(f"   created_at: {record['created_at']}")
                print(f"   status: {record['status']}")
                print()
        else:
            # Get only conversation_ids
            conversation_ids = query_by_status(project_id, args.status, args.limit)
            print(f"Found {len(conversation_ids)} records with status='{args.status}':\n")
            for i, conversation_id in enumerate(conversation_ids, 1):
                print(f"{i}. {conversation_id}")

            # Also print as a list for easy copying
            if conversation_ids:
                print("\nConversation IDs (one per line):")
                print("\n".join(conversation_ids))
    except Exception as e:
        print(f"Error querying Datastore: {e}", file=sys.stderr)
        sys.exit(1)
