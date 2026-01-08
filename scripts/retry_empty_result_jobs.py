#!/usr/bin/env python3
"""
Script to retry jobs with status='empty_result' by moving them to 'pending' status.

This script:
1. Queries Firestore for jobs with status='empty_result'
2. Moves them to 'pending' status using retry_job_from_empty_result()
3. Increments retry_count automatically
4. Ensures logs will show these as retries when processed

The script reads configuration from .env file or environment variables:
    GCP_PROJECT_ID: GCP project ID
    FIRESTORE_DATABASE: Firestore database name (default: socialnetworks)
    FIRESTORE_JOBS_COLLECTION: Firestore jobs collection name (default: pending_jobs)

Usage:
    # Retry all empty_result jobs
    poetry run python scripts/retry_empty_result_jobs.py

    # Retry with limit
    poetry run python scripts/retry_empty_result_jobs.py --limit 10

    # Retry for specific candidate
    poetry run python scripts/retry_empty_result_jobs.py --candidate-id hnd01monc

    # Dry run (show what would be retried)
    poetry run python scripts/retry_empty_result_jobs.py --dry-run
"""

import argparse
import os
import sys
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:
    print("Error: python-dotenv is not installed.")
    print("Install it with: poetry add python-dotenv")
    sys.exit(1)

# Add src to path to import trust_api modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

try:
    from google.cloud import firestore

    from trust_api.scrapping_tools.services import retry_job_from_empty_result
except ImportError as e:
    print(f"Error importing modules: {e}", file=sys.stderr)
    print(
        "Make sure you're running from the project root and dependencies are installed.",
        file=sys.stderr,
    )
    sys.exit(1)

# Load environment variables from .env file
load_dotenv()


def get_firestore_client(
    project_id: str | None = None, database_name: str = "socialnetworks"
) -> firestore.Client:
    """Initialize and return Firestore client."""
    if project_id:
        return firestore.Client(project=project_id, database=database_name)
    return firestore.Client(database=database_name)


def query_empty_result_jobs(
    collection: str = "pending_jobs",
    database_name: str = "socialnetworks",
    project_id: str | None = None,
    candidate_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """
    Query Firestore for jobs with status='empty_result'.

    Args:
        collection: Firestore collection name (default: "pending_jobs")
        database_name: Firestore database name (default: "socialnetworks")
        project_id: GCP project ID (if None, uses default from gcloud)
        candidate_id: Optional candidate_id to filter jobs
        limit: Maximum number of results to return (None for all)

    Returns:
        List of job documents with all fields, including '_doc_id' field with Firestore document ID
    """
    client = get_firestore_client(project_id, database_name)
    query = (
        client.collection(collection).where("status", "==", "empty_result").order_by("updated_at")
    )

    if candidate_id:
        query = query.where("candidate_id", "==", candidate_id)

    if limit:
        docs = query.limit(limit).stream()
    else:
        docs = query.stream()

    jobs = []
    for doc in docs:
        doc_data = doc.to_dict()
        doc_data["_doc_id"] = doc.id  # Store document ID
        jobs.append(doc_data)

    return jobs


def retry_empty_result_jobs(
    jobs_collection: str = "pending_jobs",
    database_name: str = "socialnetworks",
    project_id: str | None = None,
    candidate_id: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Retry empty_result jobs by moving them to pending status.

    Args:
        jobs_collection: Firestore jobs collection name (default: "pending_jobs")
        database_name: Firestore database name (default: "socialnetworks")
        project_id: GCP project ID (if None, uses default from gcloud)
        candidate_id: Optional candidate_id to filter jobs
        limit: Maximum number of jobs to retry (None for all)
        dry_run: If True, don't update Firestore, only report what would be retried

    Returns:
        Dictionary containing results with jobs and summary statistics
    """
    # Query empty_result jobs
    print(
        f"Querying Firestore for jobs with status='empty_result' in collection '{jobs_collection}'...",
        file=sys.stderr,
    )
    if candidate_id:
        print(f"Filtering by candidate_id: {candidate_id}", file=sys.stderr)
    jobs = query_empty_result_jobs(jobs_collection, database_name, project_id, candidate_id, limit)
    print(f"Found {len(jobs)} jobs with status='empty_result'", file=sys.stderr)

    # Process each job
    processed_jobs = []
    retried_count = 0
    error_count = 0

    for job in jobs:
        doc_id = job.get("_doc_id")
        job_id = job.get("job_id")
        post_id = job.get("post_id")
        platform = job.get("platform", "unknown")
        country = job.get("country", "unknown")
        candidate_id_job = job.get("candidate_id")
        current_retry_count = job.get("retry_count", 0)

        processed_job = {
            "doc_id": doc_id,
            "job_id": job_id,
            "post_id": post_id,
            "platform": platform,
            "country": country,
            "candidate_id": candidate_id_job,
            "current_retry_count": current_retry_count,
            "new_retry_count": current_retry_count + 1,
            "retried": False,
            "error": None,
        }

        if not doc_id:
            error_msg = "Missing _doc_id"
            processed_job["error"] = error_msg
            error_count += 1
            processed_jobs.append(processed_job)
            continue

        try:
            if dry_run:
                print(
                    f"[DRY RUN] Would retry job {doc_id} (job_id={job_id}, post_id={post_id}) "
                    f"from empty_result to pending (retry #{processed_job['new_retry_count']})",
                    file=sys.stderr,
                )
                processed_job["retried"] = True
                retried_count += 1
            else:
                # Use the helper function to retry the job
                new_retry_count = retry_job_from_empty_result(doc_id)
                processed_job["new_retry_count"] = new_retry_count
                processed_job["retried"] = True
                retried_count += 1
                print(
                    f"✓ Retried job {doc_id} (job_id={job_id}, post_id={post_id}) "
                    f"from empty_result to pending (retry #{new_retry_count})",
                    file=sys.stderr,
                )
        except Exception as e:
            error_msg = f"Error retrying job: {str(e)}"
            processed_job["error"] = error_msg
            error_count += 1
            print(f"✗ Error retrying job {doc_id}: {e}", file=sys.stderr)

        processed_jobs.append(processed_job)

    return {
        "jobs": processed_jobs,
        "summary": {
            "total_empty_result_jobs": len(jobs),
            "retried": retried_count,
            "errors": error_count,
        },
    }


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Retry jobs with status='empty_result' by moving them to 'pending' status"
    )
    parser.add_argument(
        "--jobs-collection",
        default="pending_jobs",
        help="Firestore jobs collection name (default: pending_jobs)",
    )
    parser.add_argument(
        "--database",
        default="socialnetworks",
        help="Firestore database name (default: socialnetworks)",
    )
    parser.add_argument(
        "--project-id",
        default=None,
        help="GCP project ID (default: from environment or gcloud config)",
    )
    parser.add_argument(
        "--candidate-id",
        default=None,
        help="Filter jobs by candidate_id (optional)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of jobs to retry (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be retried without actually updating Firestore",
    )

    args = parser.parse_args()

    # Get project_id from environment if not provided
    project_id = args.project_id or os.getenv("GCP_PROJECT_ID")

    if args.dry_run:
        print("=" * 60, file=sys.stderr)
        print("DRY RUN MODE - No changes will be made to Firestore", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

    # Retry empty_result jobs
    results = retry_empty_result_jobs(
        jobs_collection=args.jobs_collection,
        database_name=args.database,
        project_id=project_id,
        candidate_id=args.candidate_id,
        limit=args.limit,
        dry_run=args.dry_run,
    )

    # Print summary
    print("\n" + "=" * 60, file=sys.stderr)
    print("SUMMARY", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(
        f"Total empty_result jobs found: {results['summary']['total_empty_result_jobs']}",
        file=sys.stderr,
    )
    print(f"Jobs retried: {results['summary']['retried']}", file=sys.stderr)
    print(f"Errors: {results['summary']['errors']}", file=sys.stderr)

    # Print JSON output to stdout for programmatic use
    import json

    print(json.dumps(results, indent=2, default=str))

    # Exit with error code if there were errors
    if results["summary"]["errors"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
