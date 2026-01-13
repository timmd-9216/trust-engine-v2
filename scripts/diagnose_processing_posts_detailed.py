#!/usr/bin/env python3
"""
Script to diagnose posts with status='processing' and show detailed information
about their associated jobs, including job statuses and execution history.

Usage:
    # Diagnose all processing posts
    poetry run python scripts/diagnose_processing_posts_detailed.py

    # Export to CSV
    poetry run python scripts/diagnose_processing_posts_detailed.py --output-csv processing_diagnosis.csv
"""

import argparse
import csv
import os
import sys
from pathlib import Path
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
except ImportError as e:
    print(f"Error importing google-cloud-firestore: {e}", file=sys.stderr)
    print("Install it with: poetry add google-cloud-firestore")
    sys.exit(1)

load_dotenv()


def get_firestore_client_custom(
    project_id: str | None = None, database: str = "socialnetworks"
) -> firestore.Client:
    """Initialize and return Firestore client with custom project/database."""
    if project_id:
        return firestore.Client(project=project_id, database=database)
    return firestore.Client(database=database)


def format_timestamp(ts: Any) -> str:
    """Format a Firestore timestamp to readable string."""
    if ts is None:
        return "N/A"
    if hasattr(ts, "timestamp"):
        dt = ts
    elif isinstance(ts, str):
        return ts
    elif isinstance(ts, type(ts).__class__):
        dt = ts
    else:
        return str(ts)

    try:
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return str(ts)


def diagnose_processing_posts_detailed(
    posts_collection: str = "posts",
    jobs_collection: str = "pending_jobs",
    database: str = "socialnetworks",
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Diagnose posts with status='processing' and get detailed job information.

    Returns:
        List of post diagnosis dictionaries
    """
    client = get_firestore_client_custom(project_id, database)

    # Query posts with status='processing'
    query = client.collection(posts_collection).where("status", "==", "processing")

    diagnoses = []

    processing_posts = list(query.stream())
    print(f"Found {len(processing_posts)} posts with status='processing'\n")

    for doc in processing_posts:
        post_data = doc.to_dict()
        post_id = post_data.get("post_id", "")
        platform = post_data.get("platform", "")
        country = post_data.get("country", "")
        candidate_id = post_data.get("candidate_id", "")
        created_at = post_data.get("created_at")
        updated_at = post_data.get("updated_at")

        if not post_id:
            continue

        # Find all jobs for this post
        jobs_query = client.collection(jobs_collection).where("post_id", "==", post_id)
        jobs = []
        for job_doc in jobs_query.stream():
            job_data = job_doc.to_dict()
            job_data["_doc_id"] = job_doc.id
            jobs.append(job_data)

        # Analyze jobs
        job_statuses = {}
        active_jobs = []
        completed_jobs = []
        failed_jobs = []

        for job in jobs:
            status = job.get("status", "unknown")
            job_statuses[status] = job_statuses.get(status, 0) + 1

            job_info = {
                "job_doc_id": job.get("_doc_id", ""),
                "job_id": job.get("job_id", ""),
                "status": status,
                "created_at": format_timestamp(job.get("created_at")),
                "updated_at": format_timestamp(job.get("updated_at")),
                "retry_count": job.get("retry_count", 0),
            }

            if status in ["pending", "processing"]:
                active_jobs.append(job_info)
            elif status in ["done", "verified", "empty_result"]:
                completed_jobs.append(job_info)
            elif status in ["failed", "quota_exceeded"]:
                failed_jobs.append(job_info)

        diagnosis = {
            "post_doc_id": doc.id,
            "post_id": post_id,
            "platform": platform,
            "country": country,
            "candidate_id": candidate_id,
            "post_created_at": format_timestamp(created_at),
            "post_updated_at": format_timestamp(updated_at),
            "total_jobs": len(jobs),
            "job_statuses": job_statuses,
            "active_jobs_count": len(active_jobs),
            "completed_jobs_count": len(completed_jobs),
            "failed_jobs_count": len(failed_jobs),
            "active_jobs": active_jobs,
            "completed_jobs": completed_jobs,
            "failed_jobs": failed_jobs,
        }

        diagnoses.append(diagnosis)

        # Print summary for this post
        print(f"Post ID: {post_id}")
        print(f"  Platform: {platform}, Country: {country}, Candidate: {candidate_id}")
        print(f"  Post created: {format_timestamp(created_at)}")
        print(f"  Post updated: {format_timestamp(updated_at)}")
        print(f"  Total jobs: {len(jobs)}")
        print(f"  Job statuses: {dict(job_statuses)}")
        print(f"  Active jobs (pending/processing): {len(active_jobs)}")
        print(f"  Completed jobs (done/verified/empty_result): {len(completed_jobs)}")
        print(f"  Failed jobs (failed/quota_exceeded): {len(failed_jobs)}")

        if active_jobs:
            print("  ⏸️  Active jobs:")
            for job in active_jobs:
                print(
                    f"    - Job {job['job_doc_id'][:20]}... "
                    f"(status={job['status']}, "
                    f"created={job['created_at']}, "
                    f"updated={job['updated_at']})"
                )

        if completed_jobs:
            print("  ✅ Completed jobs:")
            for job in completed_jobs[:5]:  # Show first 5
                print(
                    f"    - Job {job['job_doc_id'][:20]}... "
                    f"(status={job['status']}, "
                    f"retry_count={job['retry_count']}, "
                    f"updated={job['updated_at']})"
                )
            if len(completed_jobs) > 5:
                print(f"    ... and {len(completed_jobs) - 5} more completed jobs")

        if failed_jobs:
            print("  ❌ Failed jobs:")
            for job in failed_jobs:
                print(
                    f"    - Job {job['job_doc_id'][:20]}... "
                    f"(status={job['status']}, "
                    f"updated={job['updated_at']})"
                )

        print()

    return diagnoses


def main():
    parser = argparse.ArgumentParser(
        description="Diagnose posts with status='processing' and their associated jobs"
    )
    parser.add_argument(
        "--posts-collection",
        type=str,
        default="posts",
        help="Firestore posts collection name (default: posts)",
    )
    parser.add_argument(
        "--jobs-collection",
        type=str,
        default="pending_jobs",
        help="Firestore jobs collection name (default: pending_jobs)",
    )
    parser.add_argument(
        "--database",
        type=str,
        default="socialnetworks",
        help="Firestore database name (default: socialnetworks)",
    )
    parser.add_argument(
        "--project-id",
        type=str,
        default=None,
        help="GCP project ID (default: from environment or ADC)",
    )
    parser.add_argument(
        "--output-csv",
        type=str,
        default=None,
        help="Output CSV file path (optional)",
    )

    args = parser.parse_args()

    # Get project_id from environment if not provided
    project_id = args.project_id or os.getenv("GCP_PROJECT_ID")

    print("=== Diagnose Processing Posts (Detailed) ===")
    print(f"Project ID: {project_id or 'from environment'}")
    print(f"Database: {args.database}")
    print(f"Posts Collection: {args.posts_collection}")
    print(f"Jobs Collection: {args.jobs_collection}")
    print()

    try:
        diagnoses = diagnose_processing_posts_detailed(
            posts_collection=args.posts_collection,
            jobs_collection=args.jobs_collection,
            database=args.database,
            project_id=project_id,
        )

        # Print summary
        print("=" * 60)
        print("Summary:")
        print("=" * 60)
        print(f"Total posts with status='processing': {len(diagnoses)}")

        if diagnoses:
            posts_with_active = sum(1 for d in diagnoses if d["active_jobs_count"] > 0)
            posts_without_active = sum(1 for d in diagnoses if d["active_jobs_count"] == 0)

            print(f"Posts with active jobs: {posts_with_active}")
            print(f"Posts without active jobs: {posts_without_active}")

            # Count by job status
            all_statuses = {}
            for diagnosis in diagnoses:
                for status, count in diagnosis["job_statuses"].items():
                    all_statuses[status] = all_statuses.get(status, 0) + count

            print("\nTotal jobs by status:")
            for status, count in sorted(all_statuses.items()):
                print(f"  {status}: {count}")

        # Export to CSV if requested
        if args.output_csv and diagnoses:
            csv_path = Path(args.output_csv)
            csv_path.parent.mkdir(parents=True, exist_ok=True)

            # Flatten data for CSV
            csv_rows = []
            for diagnosis in diagnoses:
                # Create one row per post with summary info
                row = {
                    "post_doc_id": diagnosis["post_doc_id"],
                    "post_id": diagnosis["post_id"],
                    "platform": diagnosis["platform"],
                    "country": diagnosis["country"],
                    "candidate_id": diagnosis["candidate_id"],
                    "post_created_at": diagnosis["post_created_at"],
                    "post_updated_at": diagnosis["post_updated_at"],
                    "total_jobs": diagnosis["total_jobs"],
                    "active_jobs": diagnosis["active_jobs_count"],
                    "completed_jobs": diagnosis["completed_jobs_count"],
                    "failed_jobs": diagnosis["failed_jobs_count"],
                    "job_statuses": ", ".join(
                        f"{k}:{v}" for k, v in diagnosis["job_statuses"].items()
                    ),
                }
                csv_rows.append(row)

            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                if csv_rows:
                    fieldnames = csv_rows[0].keys()
                    writer = csv.DictWriter(f, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(csv_rows)

            print(f"\nExported {len(csv_rows)} posts to {csv_path}")

    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
