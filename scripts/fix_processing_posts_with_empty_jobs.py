#!/usr/bin/env python3
"""
Script to fix posts with status='processing' that only have empty_result/verified jobs.

When a job finishes with empty_result, the post should not remain in 'processing' state
if there are no active jobs (pending/processing).

Usage:
    # Dry run (see what would be fixed)
    poetry run python scripts/fix_processing_posts_with_empty_jobs.py --dry-run

    # Fix posts (update to 'noreplies' or 'finished')
    poetry run python scripts/fix_processing_posts_with_empty_jobs.py --new-status noreplies

    # Fix posts and update to 'finished'
    poetry run python scripts/fix_processing_posts_with_empty_jobs.py --new-status finished
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


def has_active_jobs(jobs: list[dict[str, Any]]) -> bool:
    """
    Check if there are any active jobs (pending or processing).

    Args:
        jobs: List of job documents

    Returns:
        True if there are active jobs, False otherwise
    """
    for job in jobs:
        status = job.get("status", "")
        if status in ["pending", "processing"]:
            return True
    return False


def determine_post_status_from_jobs(jobs: list[dict[str, Any]]) -> str | None:
    """
    Determine the new post status based on job statuses.

    Rules:
    - If any job is 'verified' -> post should be 'done'
    - If any job is 'empty_result' or 'processing' -> post should be 'finished'
    - If all jobs are 'done' -> post should be 'done'
    - If any job is 'failed' or 'quota_exceeded' -> post should be 'noreplies' (to allow retry)
    - Otherwise -> None (keep current status)

    Args:
        jobs: List of job documents

    Returns:
        New status for the post, or None if should keep current status
    """
    if not jobs:
        return None

    # Collect all job statuses
    job_statuses = [job.get("status", "") for job in jobs]

    # Priority 1: If any job is 'verified', post should be 'done'
    if "verified" in job_statuses:
        return "done"

    # Priority 2: If any job is 'done', post should be 'done'
    if "done" in job_statuses:
        return "done"

    # Priority 3: If any job is 'empty_result', post should be 'done'
    if "empty_result" in job_statuses:
        return "done"

    # Priority 4: If any job is 'processing' (but no empty_result), post should be 'finished'
    if "processing" in job_statuses:
        return "finished"

    # Priority 4: If all jobs are 'failed' or 'quota_exceeded', post should be 'noreplies' (to allow retry)
    if all(status in ["failed", "quota_exceeded"] for status in job_statuses):
        return "noreplies"

    # Default: keep current status
    return None


def update_post_status_custom(
    client: firestore.Client,
    posts_collection: str,
    doc_id: str,
    new_status: str,
    dry_run: bool = False,
) -> bool:
    """Update post status in Firestore."""
    if dry_run:
        print(f"  [DRY RUN] Would update post {doc_id} to '{new_status}'")
        return True

    try:
        from datetime import datetime, timezone

        doc_ref = client.collection(posts_collection).document(doc_id)
        now = datetime.now(timezone.utc)
        doc_ref.update({"status": new_status, "updated_at": now})
        return True
    except Exception as e:
        print(f"  ERROR updating post {doc_id}: {e}")
        return False


def fix_processing_posts(
    posts_collection: str = "posts",
    jobs_collection: str = "pending_jobs",
    database: str = "socialnetworks",
    project_id: str | None = None,
    new_status: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Fix posts with status='processing' that only have empty_result/verified jobs.

    Returns:
        Dictionary with fix results
    """
    client = get_firestore_client_custom(project_id, database)

    # Query posts with status='processing'
    query = client.collection(posts_collection).where("status", "==", "processing")

    results = {
        "total_processing_posts": 0,
        "posts_with_active_jobs": 0,
        "posts_without_active_jobs": 0,
        "posts_fixed": 0,
        "errors": 0,
        "fixed_posts": [],
    }

    processing_posts = list(query.stream())
    results["total_processing_posts"] = len(processing_posts)

    print(f"Found {results['total_processing_posts']} posts with status='processing'\n")

    for doc in processing_posts:
        post_data = doc.to_dict()
        post_id = post_data.get("post_id", "")
        platform = post_data.get("platform", "")
        country = post_data.get("country", "")
        candidate_id = post_data.get("candidate_id", "")

        if not post_id:
            continue

        # Find all jobs for this post
        jobs_query = client.collection(jobs_collection).where("post_id", "==", post_id)
        jobs = []
        for job_doc in jobs_query.stream():
            job_data = job_doc.to_dict()
            job_data["_doc_id"] = job_doc.id
            jobs.append(job_data)

        # Check if there are active jobs
        if has_active_jobs(jobs):
            results["posts_with_active_jobs"] += 1
            print(f"  ⏸️  post_id={post_id}, platform={platform} - " f"Has active jobs (skipping)")
            continue

        # No active jobs - this post should be fixed
        results["posts_without_active_jobs"] += 1

        # Get job statuses for info
        job_statuses = {}
        for job in jobs:
            status = job.get("status", "unknown")
            job_statuses[status] = job_statuses.get(status, 0) + 1

        # Determine new status based on job statuses
        if new_status is None:
            determined_status = determine_post_status_from_jobs(jobs)
            if determined_status is None:
                print(
                    f"  ⚠️  post_id={post_id}, platform={platform}, "
                    f"jobs={len(jobs)} (statuses: {', '.join(job_statuses.keys())}) - "
                    f"Could not determine new status, skipping"
                )
                continue
            post_new_status = determined_status
        else:
            post_new_status = new_status

        print(
            f"  🔧 post_id={post_id}, platform={platform}, "
            f"jobs={len(jobs)} (statuses: {', '.join(job_statuses.keys())})"
        )

        # Update post status
        if update_post_status_custom(client, posts_collection, doc.id, post_new_status, dry_run):
            results["posts_fixed"] += 1
            results["fixed_posts"].append(
                {
                    "post_doc_id": doc.id,
                    "post_id": post_id,
                    "platform": platform,
                    "country": country,
                    "candidate_id": candidate_id,
                    "jobs_count": len(jobs),
                    "job_statuses": job_statuses,
                    "new_status": post_new_status,
                }
            )
            print(f"      Updated to '{post_new_status}'")
        else:
            results["errors"] += 1

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Fix posts with status='processing' that only have empty_result jobs"
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
        "--new-status",
        type=str,
        default=None,
        help="New status to set for fixed posts (default: auto-detect from job statuses). Options: noreplies, finished, done, or None for auto",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be fixed without making changes",
    )

    args = parser.parse_args()

    # Get project_id from environment if not provided
    project_id = args.project_id or os.getenv("GCP_PROJECT_ID")

    print("=== Fix Processing Posts with Empty Jobs ===")
    print(f"Project ID: {project_id or 'from environment'}")
    print(f"Database: {args.database}")
    print(f"Posts Collection: {args.posts_collection}")
    print(f"Jobs Collection: {args.jobs_collection}")
    if args.new_status:
        print(f"New status: {args.new_status} (manual)")
    else:
        print("New status: auto-detect from job statuses")
        print("  Rules:")
        print("    - If job is 'verified' -> post = 'done'")
        print("    - If job is 'empty_result' -> post = 'done'")
        print("    - If job is 'done' -> post = 'done'")
        print("    - If job is 'processing' -> post = 'finished'")
        print("    - If all jobs are 'failed'/'quota_exceeded' -> post = 'noreplies'")
    print(f"Dry run: {args.dry_run}")
    print()

    try:
        results = fix_processing_posts(
            posts_collection=args.posts_collection,
            jobs_collection=args.jobs_collection,
            database=args.database,
            project_id=project_id,
            new_status=args.new_status,
            dry_run=args.dry_run,
        )

        # Print summary
        print("\n" + "=" * 60)
        print("Summary:")
        print("=" * 60)
        print(f"Total posts with status='processing': {results['total_processing_posts']}")
        print(f"Posts with active jobs (skipped): {results['posts_with_active_jobs']}")
        print(f"Posts without active jobs (to fix): {results['posts_without_active_jobs']}")
        print(f"Posts fixed: {results['posts_fixed']}")
        print(f"Errors: {results['errors']}")

        if results["fixed_posts"]:
            print(f"\n✅ Fixed posts ({len(results['fixed_posts'])}):")
            for post in results["fixed_posts"][:10]:  # Show first 10
                print(
                    f"  - post_id={post['post_id']}, "
                    f"platform={post['platform']}, "
                    f"jobs={post['jobs_count']}, "
                    f"statuses={list(post['job_statuses'].keys())}, "
                    f"new_status={post['new_status']}"
                )
            if len(results["fixed_posts"]) > 10:
                print(f"  ... and {len(results['fixed_posts']) - 10} more")

        if args.dry_run:
            print("\n[DRY RUN] No changes were made. Run without --dry-run to apply fixes.")

    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
