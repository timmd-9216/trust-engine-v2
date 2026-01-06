#!/usr/bin/env python3
"""
Quick script to count jobs with status='failed' in the pending_jobs collection.
"""

import os
import sys

try:
    from dotenv import load_dotenv
    from google.cloud import firestore
except ImportError:
    print("Error: Required packages not installed.")
    print("Install with: poetry install")
    sys.exit(1)

# Load environment variables
load_dotenv()

# Get configuration
project_id = os.getenv("GCP_PROJECT_ID")
database_name = os.getenv("FIRESTORE_DATABASE", "socialnetworks")
collection = os.getenv("FIRESTORE_JOBS_COLLECTION", "pending_jobs")

# Initialize Firestore client
if project_id:
    client = firestore.Client(project=project_id, database=database_name)
else:
    client = firestore.Client(database=database_name)

# Query failed jobs
print("Querying Firestore for jobs with status='failed'...")
print(f"Database: {database_name}")
print(f"Collection: {collection}")
print(f"Project: {project_id or 'default from gcloud'}")
print()

try:
    query = client.collection(collection).where("status", "==", "failed")
    docs = list(query.stream())
    count = len(docs)

    print(f"Total jobs with status='failed': {count}")

    if count > 0:
        # Count by candidate_id
        candidate_counts = {}
        for doc in docs:
            data = doc.to_dict()
            candidate_id = data.get("candidate_id", "unknown")
            candidate_counts[candidate_id] = candidate_counts.get(candidate_id, 0) + 1

        print("\nBy candidate_id:")
        for candidate_id, cnt in sorted(candidate_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  {candidate_id}: {cnt}")

        # Count by platform
        platform_counts = {}
        for doc in docs:
            data = doc.to_dict()
            platform = data.get("platform", "unknown")
            platform_counts[platform] = platform_counts.get(platform, 0) + 1

        print("\nBy platform:")
        for platform, cnt in sorted(platform_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"  {platform}: {cnt}")

except Exception as e:
    print(f"Error querying Firestore: {e}", file=sys.stderr)
    sys.exit(1)
