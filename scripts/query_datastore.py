#!/usr/bin/env python3
"""
Script to query Firestore for social posts with a specific status.

Queries the specified Firestore database and collection for records matching the specified status
and returns their conversation_id_str values.

The script reads GCP_PROJECT_ID from .env file (or command line argument).
Create a .env file in the project root with:
    GCP_PROJECT_ID=your-project-id
"""

import os
import sys

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


def query_by_status(
    collection: str,
    database_name: str = "socialnetworks",
    project_id: str = None,
    status: str = "scrapped",
    limit: int = None,
):
    """
    Query Firestore for records with a specific status.

    Args:
        collection: Firestore collection name
        database_name: Firestore database name (default: "socialnetworks")
        project_id: GCP project ID (if None, uses default from gcloud)
        status: Status value to filter by (default: "scrapped")
        limit: Maximum number of results to return (None for all)

    Returns:
        List of conversation_id_str values
    """
    # Initialize Firestore client
    if project_id:
        client = firestore.Client(project=project_id, database=database_name)
    else:
        client = firestore.Client(database=database_name)

    # Create query
    query = client.collection(collection).where("status", "==", status)

    # Apply limit if specified
    if limit:
        docs = query.limit(limit).stream()
    else:
        docs = query.stream()

    # Extract conversation_id_str values
    conversation_ids = []
    for doc in docs:
        doc_data = doc.to_dict()
        conversation_id = doc_data.get("conversation_id_str", "")
        if conversation_id:
            conversation_ids.append(conversation_id)

    return conversation_ids


def query_with_details(
    collection: str,
    database_name: str = "socialnetworks",
    project_id: str = None,
    status: str = "scrapped",
    limit: int = None,
):
    """
    Query Firestore for records with a specific status and return full details.

    Args:
        collection: Firestore collection name
        database_name: Firestore database name (default: "socialnetworks")
        project_id: GCP project ID (if None, uses default from gcloud)
        status: Status value to filter by (default: "scrapped")
        limit: Maximum number of results to return (None for all)

    Returns:
        List of dictionaries with record details
    """
    # Initialize Firestore client
    if project_id:
        client = firestore.Client(project=project_id, database=database_name)
    else:
        client = firestore.Client(database=database_name)

    # Create query
    query = client.collection(collection).where("status", "==", status)

    # Apply limit if specified
    if limit:
        docs = query.limit(limit).stream()
    else:
        docs = query.stream()

    # Extract full details
    records = []
    for doc in docs:
        doc_data = doc.to_dict()
        record = {
            "conversation_id_str": doc_data.get("conversation_id_str", ""),
            "platform": doc_data.get("platform", ""),
            "created_at": doc_data.get("created_at", ""),
            "status": doc_data.get("status", ""),
        }
        records.append(record)

    return records


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Query Firestore for social posts by status")
    parser.add_argument(
        "collection",
        type=str,
        help="Firestore collection name",
    )
    parser.add_argument(
        "--status",
        type=str,
        default="scrapped",
        help='Status to filter by (default: "scrapped")',
    )
    parser.add_argument(
        "--database",
        type=str,
        default="socialnetworks",
        help="Firestore database name (default: socialnetworks)",
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

    print(f"Querying Firestore database '{args.database}'...")
    print(f"Collection: {args.collection}")
    print(f"Status filter: {args.status}")
    print(f"Project ID: {project_id or 'default from gcloud'}")
    if args.limit:
        print(f"Limit: {args.limit}")
    print()

    try:
        if args.details:
            # Get full details
            records = query_with_details(
                args.collection, args.database, project_id, args.status, args.limit
            )
            print(f"Found {len(records)} records:\n")
            for i, record in enumerate(records, 1):
                print(f"{i}. conversation_id: {record['conversation_id_str']}")
                print(f"   platform: {record['platform']}")
                print(f"   created_at: {record['created_at']}")
                print(f"   status: {record['status']}")
                print()
        else:
            # Get only conversation_ids
            conversation_ids = query_by_status(
                args.collection, args.database, project_id, args.status, args.limit
            )
            print(f"Found {len(conversation_ids)} records with status='{args.status}':\n")
            for i, conversation_id in enumerate(conversation_ids, 1):
                print(f"{i}. {conversation_id}")

            # Also print as a list for easy copying
            if conversation_ids:
                print("\nConversation IDs (one per line):")
                print("\n".join(conversation_ids))
    except Exception as e:
        print(f"Error querying Firestore: {e}", file=sys.stderr)
        sys.exit(1)
