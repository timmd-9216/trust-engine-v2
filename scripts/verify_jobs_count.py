#!/usr/bin/env python3
"""
Verify job counts in Firestore (pending_jobs).

Checks empty_result, failed, and other statuses directly via Firestore
and via trust_api services (same as dashboard). Use to debug discrepancies.

Usage:
    poetry run python scripts/verify_jobs_count.py
"""

import os
import sys

try:
    from dotenv import load_dotenv
except ImportError:
    print("Error: python-dotenv not installed.")
    sys.exit(1)

load_dotenv()

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

try:
    from google.cloud import firestore

    from trust_api.scrapping_tools.core.config import settings
    from trust_api.scrapping_tools.services import (
        count_failed_jobs_without_done,
        count_jobs_by_status,
    )
except ImportError as e:
    print(f"Error importing: {e}", file=sys.stderr)
    sys.exit(1)


def direct_count(client: firestore.Client, status: str) -> int:
    """Count jobs with status via direct Firestore query."""
    coll = settings.firestore_jobs_collection
    query = client.collection(coll).where("status", "==", status)
    return sum(1 for _ in query.stream())


def main() -> int:
    print("=" * 60)
    print("Verify Jobs Count (pending_jobs)")
    print("=" * 60)
    print(f"Database: {settings.firestore_database}")
    print(f"Collection: {settings.firestore_jobs_collection}")
    print(f"Project: {settings.gcp_project_id or 'default from gcloud'}")
    print()

    if settings.gcp_project_id:
        client = firestore.Client(
            project=settings.gcp_project_id, database=settings.firestore_database
        )
    else:
        client = firestore.Client(database=settings.firestore_database)

    statuses = ["pending", "processing", "done", "failed", "empty_result", "verified"]
    print("Direct Firestore query (status == X):")
    print("-" * 40)
    for status in statuses:
        try:
            count = direct_count(client, status)
            print(f"  {status}: {count}")
        except Exception as e:
            print(f"  {status}: ERROR - {e}")

    print()
    print("trust_api services (same as dashboard):")
    print("-" * 40)
    for status in statuses:
        try:
            if status == "failed":
                count = count_failed_jobs_without_done()
            else:
                count = count_jobs_by_status(status=status)
            extra = " (failed_without_done)" if status == "failed" else ""
            print(f"  {status}{extra}: {count}")
        except Exception as e:
            print(f"  {status}: ERROR - {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
