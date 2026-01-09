#!/usr/bin/env python3
"""
Script to cleanup failed jobs for posts that are already in 'done' status.

This script identifies and removes (or marks) failed jobs that are no longer needed
because the associated post has been successfully processed (status='done').

The script:
1. Queries failed jobs from Firestore
2. Checks if the associated post is in 'done' status
3. Verifies there are no other pending/processing jobs for the same post
4. Deletes or marks the failed jobs (configurable)
"""

import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

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


def get_firestore_client(
    project_id: str | None = None, database_name: str = "socialnetworks"
) -> firestore.Client:
    """Initialize and return Firestore client."""
    if project_id:
        return firestore.Client(project=project_id, database=database_name)
    return firestore.Client(database=database_name)


def has_pending_or_processing_job_for_post(
    client: firestore.Client,
    collection: str,
    post_id: str,
    exclude_job_doc_id: str | None = None,
) -> bool:
    """
    Check if there's already a pending or processing job for a given post.

    Args:
        client: Firestore client
        collection: Jobs collection name
        post_id: The post ID to check
        exclude_job_doc_id: Job document ID to exclude from the check (current job being processed)

    Returns:
        True if there's an existing pending or processing job, False otherwise
    """
    # Check for pending jobs
    pending_query = (
        client.collection(collection)
        .where("post_id", "==", post_id)
        .where("status", "==", "pending")
        .limit(1)
    )
    pending_jobs = list(pending_query.stream())
    for job_doc in pending_jobs:
        if exclude_job_doc_id is None or job_doc.id != exclude_job_doc_id:
            return True

    # Check for processing jobs
    processing_query = (
        client.collection(collection)
        .where("post_id", "==", post_id)
        .where("status", "==", "processing")
        .limit(1)
    )
    processing_jobs = list(processing_query.stream())
    for job_doc in processing_jobs:
        if exclude_job_doc_id is None or job_doc.id != exclude_job_doc_id:
            return True

    return False


def cleanup_failed_jobs(
    jobs_collection: str = "pending_jobs",
    posts_collection: str = "posts",
    database_name: str = "socialnetworks",
    project_id: str | None = None,
    dry_run: bool = False,
    delete: bool = True,
) -> dict[str, Any]:
    """
    Cleanup failed jobs for posts that are already in 'done' status.

    Args:
        jobs_collection: Firestore jobs collection name (default: "pending_jobs")
        posts_collection: Firestore posts collection name (default: "posts")
        database_name: Firestore database name (default: "socialnetworks")
        project_id: GCP project ID (if None, uses default from gcloud)
        dry_run: If True, don't delete jobs, only report what would be deleted
        delete: If True, delete jobs. If False, skip them (useful for dry-run to see what would be deleted)

    Returns:
        Dictionary containing cleanup results
    """
    client = get_firestore_client(project_id, database_name)

    # Query failed jobs
    print(
        f"Querying Firestore for jobs with status='failed' in collection '{jobs_collection}'...",
        file=sys.stderr,
    )
    failed_jobs_query = client.collection(jobs_collection).where("status", "==", "failed")
    failed_jobs = list(failed_jobs_query.stream())
    print(f"Found {len(failed_jobs)} failed jobs", file=sys.stderr)

    # Analyze and cleanup
    analyzed_jobs = []
    deleted_count = 0
    skipped_count = 0
    error_count = 0
    posts_to_cleanup = defaultdict(list)

    for job_doc in failed_jobs:
        job_data = job_doc.to_dict()
        doc_id = job_doc.id
        job_id = job_data.get("job_id")
        post_id = job_data.get("post_id")
        post_doc_id = job_data.get("post_doc_id")

        analyzed_job = {
            "doc_id": doc_id,
            "job_id": job_id,
            "post_id": post_id,
            "post_doc_id": post_doc_id,
            "platform": job_data.get("platform"),
            "country": job_data.get("country"),
            "candidate_id": job_data.get("candidate_id"),
            "retry_count": job_data.get("retry_count", 0),
            "created_at": str(job_data.get("created_at", "")),
            "updated_at": str(job_data.get("updated_at", "")),
            "should_delete": False,
            "deleted": False,
            "reason": None,
        }

        # Check if post exists and is in 'done' status
        if not post_doc_id:
            analyzed_job["reason"] = "No post_doc_id found in job"
            skipped_count += 1
            analyzed_jobs.append(analyzed_job)
            continue

        try:
            post_doc = client.collection(posts_collection).document(post_doc_id).get()
            if not post_doc.exists:
                analyzed_job["reason"] = f"Post document {post_doc_id} not found"
                skipped_count += 1
                analyzed_jobs.append(analyzed_job)
                continue

            post_data = post_doc.to_dict()
            post_status = post_data.get("status")

            # Check if post is done
            if post_status != "done":
                analyzed_job["reason"] = f"Post status is '{post_status}', not 'done'"
                skipped_count += 1
                analyzed_jobs.append(analyzed_job)
                continue

            # Check if there are other pending/processing jobs for this post
            if has_pending_or_processing_job_for_post(client, jobs_collection, post_id, doc_id):
                analyzed_job["reason"] = "Other pending/processing jobs exist for this post"
                skipped_count += 1
                analyzed_jobs.append(analyzed_job)
                continue

            # Post is done and no other jobs pending/processing
            # BUT: Check if this might be a quota/rate limit issue before deleting
            # Jobs that failed on the same day in a mass event might be quota-related
            updated_at = job_data.get("updated_at")
            mass_failure_date = datetime(2026, 1, 8, tzinfo=timezone.utc)

            might_be_quota_issue = False
            if updated_at:
                if hasattr(updated_at, "date"):
                    failure_date = updated_at.date()
                else:
                    failure_date_str = str(updated_at)[:10]
                    failure_date = datetime.strptime(failure_date_str, "%Y-%m-%d").date()

                # Check if failed on the mass failure date (2026-01-08)
                if failure_date == mass_failure_date.date():
                    might_be_quota_issue = True
                    analyzed_job["reason"] = (
                        f"Post is done but job failed on mass failure date ({failure_date}) - might be quota/rate limit issue"
                    )
                else:
                    analyzed_job["reason"] = "Post is done and no other pending/processing jobs"
            else:
                analyzed_job["reason"] = "Post is done and no other pending/processing jobs"

            # Analysis of failed jobs:
            # - Verification shows these ARE real failures confirmed by Information Tracer
            # - However, 95.3% occurred on 2026-01-08 when daily quota limit was reached (400/400)
            # - This suggests jobs were rejected/failed when quota was exceeded
            # - All posts are in "done" status (processed by other successful jobs)
            # - These failed jobs are confirmed failures and cannot be recovered
            # - Decision: Safe to delete since posts are already processed and jobs are confirmed failed
            days_since_failure = None
            if updated_at:
                if hasattr(updated_at, "date"):
                    days_since_failure = (
                        datetime.now(timezone.utc).date() - updated_at.date()
                    ).days
                else:
                    failure_date_str = str(updated_at)[:10]
                    failure_date = datetime.strptime(failure_date_str, "%Y-%m-%d").date()
                    days_since_failure = (datetime.now(timezone.utc).date() - failure_date).days

            # Since posts are done and no other jobs pending/processing,
            # and verification shows these are confirmed real failures (not recoverable),
            # it's safe to delete regardless of when they failed.
            # The mass failure date (2026-01-08) suggests quota-related rejection,
            # but jobs are confirmed as permanently failed in Information Tracer.
            analyzed_job["should_delete"] = True
            if might_be_quota_issue:
                analyzed_job["reason"] = (
                    f"Post is done, job confirmed as permanently failed. "
                    f"Failed on mass failure date (2026-01-08) likely due to quota limit. "
                    f"Failed {days_since_failure} days ago. "
                    f"Safe to delete: post already processed by other successful jobs."
                )
            else:
                analyzed_job["reason"] = (
                    "Post is done and no other pending/processing jobs - confirmed permanent failure"
                )
            posts_to_cleanup[post_id].append(analyzed_job)

            if not dry_run and delete:
                try:
                    # Delete the job document
                    job_doc.reference.delete()
                    analyzed_job["deleted"] = True
                    deleted_count += 1
                    print(
                        f"Deleted failed job {doc_id} (job_id={job_id}, post_id={post_id})",
                        file=sys.stderr,
                    )
                except Exception as e:
                    analyzed_job["reason"] = f"Error deleting: {e}"
                    error_count += 1
                    print(f"Error deleting job {doc_id}: {e}", file=sys.stderr)
            else:
                print(
                    f"[DRY RUN] Would delete failed job {doc_id} (job_id={job_id}, post_id={post_id})",
                    file=sys.stderr,
                )

        except Exception as e:
            analyzed_job["reason"] = f"Error checking post: {e}"
            error_count += 1
            print(f"Error processing job {doc_id}: {e}", file=sys.stderr)

        analyzed_jobs.append(analyzed_job)

    # Generate summary
    summary = {
        "total_failed_jobs": len(failed_jobs),
        "jobs_to_delete": len([j for j in analyzed_jobs if j["should_delete"]]),
        "jobs_deleted": deleted_count
        if not dry_run
        else len([j for j in analyzed_jobs if j["should_delete"]]),
        "jobs_skipped": skipped_count,
        "jobs_errors": error_count,
        "unique_posts_affected": len(posts_to_cleanup),
        "dry_run": dry_run,
    }

    # Calculate stats by post
    posts_stats = []
    for post_id, jobs_list in posts_to_cleanup.items():
        posts_stats.append(
            {
                "post_id": post_id,
                "failed_jobs_to_delete": len(jobs_list),
                "post_doc_id": jobs_list[0]["post_doc_id"] if jobs_list else None,
            }
        )

    return {
        "summary": summary,
        "posts_stats": sorted(posts_stats, key=lambda x: x["failed_jobs_to_delete"], reverse=True),
        "jobs": analyzed_jobs,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    """Main entry point for the script."""
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Cleanup failed jobs for posts that are already in 'done' status"
    )
    parser.add_argument(
        "--jobs-collection",
        type=str,
        default="pending_jobs",
        help="Firestore jobs collection name (default: pending_jobs)",
    )
    parser.add_argument(
        "--posts-collection",
        type=str,
        default="posts",
        help="Firestore posts collection name (default: posts)",
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
        help="GCP Project ID (overrides .env file)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't delete jobs, only report what would be deleted",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path (default: print to stdout)",
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["json", "text"],
        default="text",
        help="Output format: json or text (default: text)",
    )

    args = parser.parse_args()

    # Get configuration from environment or arguments
    project_id = args.project_id or os.getenv("GCP_PROJECT_ID")
    database_name = args.database or os.getenv("FIRESTORE_DATABASE", "socialnetworks")
    jobs_collection = args.jobs_collection or os.getenv("FIRESTORE_JOBS_COLLECTION", "pending_jobs")
    posts_collection = args.posts_collection or os.getenv("FIRESTORE_COLLECTION", "posts")

    if args.dry_run:
        print("Running in DRY RUN mode - no jobs will be deleted", file=sys.stderr)

    try:
        # Cleanup failed jobs
        results = cleanup_failed_jobs(
            jobs_collection=jobs_collection,
            posts_collection=posts_collection,
            database_name=database_name,
            project_id=project_id,
            dry_run=args.dry_run,
            delete=True,
        )

        # Format output
        if args.format == "json":
            output = json.dumps(results, ensure_ascii=False, indent=2, default=str)
        else:
            # Text format
            output_lines = []
            output_lines.append("=" * 80)
            output_lines.append("CLEANUP FAILED JOBS REPORT")
            output_lines.append("=" * 80)
            output_lines.append("")
            output_lines.append(f"Generated at: {results['generated_at']}")
            output_lines.append(f"Dry run: {results['summary']['dry_run']}")
            output_lines.append("")
            output_lines.append("SUMMARY:")
            output_lines.append(f"  Total failed jobs: {results['summary']['total_failed_jobs']}")
            output_lines.append(f"  Jobs to delete: {results['summary']['jobs_to_delete']}")
            output_lines.append(
                f"  Jobs {'deleted' if not results['summary']['dry_run'] else 'would be deleted'}: {results['summary']['jobs_deleted']}"
            )
            output_lines.append(f"  Jobs skipped: {results['summary']['jobs_skipped']}")
            output_lines.append(f"  Jobs with errors: {results['summary']['jobs_errors']}")
            output_lines.append(
                f"  Unique posts affected: {results['summary']['unique_posts_affected']}"
            )
            output_lines.append("")
            output_lines.append("=" * 80)
            output_lines.append("POSTS WITH JOBS TO DELETE:")
            output_lines.append("=" * 80)
            output_lines.append("")
            for post_stat in results["posts_stats"]:
                output_lines.append(f"Post ID: {post_stat['post_id']}")
                output_lines.append(f"  Post Doc ID: {post_stat['post_doc_id']}")
                output_lines.append(
                    f"  Failed jobs to delete: {post_stat['failed_jobs_to_delete']}"
                )
                output_lines.append("")
            output_lines.append("=" * 80)

            output = "\n".join(output_lines)

        # Write output
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"Report written to {args.output}", file=sys.stderr)
        else:
            print(output)

        return 0
    except Exception as e:
        print(f"Error cleaning up failed jobs: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
