#!/usr/bin/env python3
"""
Script to verify empty_result jobs and update status to 'verified' for Twitter posts
with replies_count <= 2.

Queries Firestore for jobs with status='empty_result', checks the associated post
document for platform='twitter' and replies_count <= 2, and updates the job status
to 'verified' if conditions are met.

The script reads configuration from .env file or environment variables:
    GCP_PROJECT_ID: GCP project ID
    FIRESTORE_DATABASE: Firestore database name (default: socialnetworks)
    FIRESTORE_JOBS_COLLECTION: Firestore jobs collection name (default: pending_jobs)
    FIRESTORE_COLLECTION: Firestore posts collection name (default: posts)
"""

import os
import sys
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


def get_post_document(
    client: firestore.Client,
    posts_collection: str,
    post_doc_id: str,
) -> dict[str, Any] | None:
    """
    Get a post document from Firestore by document ID.

    Args:
        client: Firestore client
        posts_collection: Posts collection name
        post_doc_id: Post document ID

    Returns:
        Post document data as dict, or None if not found
    """
    try:
        doc_ref = client.collection(posts_collection).document(post_doc_id)
        doc = doc_ref.get()
        if doc.exists:
            return doc.to_dict()
        return None
    except Exception as e:
        print(f"Error getting post document {post_doc_id}: {e}", file=sys.stderr)
        return None


def update_job_status_in_firestore(
    client: firestore.Client,
    collection: str,
    doc_id: str,
    new_status: str,
) -> None:
    """
    Update the status field of a job document in Firestore.

    Args:
        client: Firestore client
        collection: Collection name
        doc_id: Document ID
        new_status: New status value
    """
    doc_ref = client.collection(collection).document(doc_id)
    now = datetime.now(timezone.utc)
    doc_ref.update({"status": new_status, "updated_at": now})


def verify_and_update_empty_jobs(
    jobs_collection: str = "pending_jobs",
    posts_collection: str = "posts",
    database_name: str = "socialnetworks",
    project_id: str | None = None,
    candidate_id: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Verify empty_result jobs and update status to 'verified' if conditions are met.

    Args:
        jobs_collection: Firestore jobs collection name (default: "pending_jobs")
        posts_collection: Firestore posts collection name (default: "posts")
        database_name: Firestore database name (default: "socialnetworks")
        project_id: GCP project ID (if None, uses default from gcloud)
        candidate_id: Optional candidate_id to filter jobs
        limit: Maximum number of jobs to analyze (None for all)
        dry_run: If True, don't update Firestore, only report what would be updated

    Returns:
        Dictionary containing analysis results with jobs and summary statistics
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

    # Get Firestore client
    firestore_client = get_firestore_client(project_id, database_name)

    # Analyze each job
    analyzed_jobs = []
    updated_count = 0
    verified_count = 0
    skipped_count = 0
    error_count = 0

    for job in jobs:
        doc_id = job.get("_doc_id")
        job_id = job.get("job_id")
        post_doc_id = job.get("post_doc_id")
        platform = job.get("platform", "").lower()
        candidate_id_job = job.get("candidate_id")

        analyzed_job = {
            "doc_id": doc_id,
            "job_id": job_id,
            "post_id": job.get("post_id"),
            "post_doc_id": post_doc_id,
            "platform": platform,
            "country": job.get("country"),
            "candidate_id": candidate_id_job,
            "should_update": False,
            "new_status": None,
            "updated": False,
            "reason": None,
        }

        # Check if platform is twitter
        if platform != "twitter":
            analyzed_job["reason"] = f"Platform is '{platform}', not 'twitter'"
            skipped_count += 1
            analyzed_jobs.append(analyzed_job)
            continue

        # Get post document to check replies_count
        if not post_doc_id:
            analyzed_job["reason"] = "No post_doc_id found in job"
            error_count += 1
            analyzed_jobs.append(analyzed_job)
            continue

        post_data = get_post_document(firestore_client, posts_collection, post_doc_id)
        if not post_data:
            analyzed_job["reason"] = f"Post document {post_doc_id} not found"
            error_count += 1
            analyzed_jobs.append(analyzed_job)
            continue

        replies_count = post_data.get("replies_count")
        analyzed_job["replies_count"] = replies_count

        # Check if replies_count <= 2
        if replies_count is None:
            analyzed_job["reason"] = "replies_count is None in post document"
            skipped_count += 1
            analyzed_jobs.append(analyzed_job)
            continue

        try:
            replies_count_int = int(replies_count)
        except (ValueError, TypeError):
            analyzed_job["reason"] = f"replies_count '{replies_count}' cannot be converted to int"
            skipped_count += 1
            analyzed_jobs.append(analyzed_job)
            continue

        if replies_count_int > 2:
            analyzed_job["reason"] = f"replies_count ({replies_count_int}) > 2"
            skipped_count += 1
            analyzed_jobs.append(analyzed_job)
            continue

        # Conditions met: platform is twitter and replies_count <= 2
        analyzed_job["should_update"] = True
        analyzed_job["new_status"] = "verified"
        analyzed_job["reason"] = f"Platform is twitter and replies_count ({replies_count_int}) <= 2"
        verified_count += 1

        if not dry_run:
            try:
                update_job_status_in_firestore(
                    firestore_client, jobs_collection, doc_id, "verified"
                )
                analyzed_job["updated"] = True
                updated_count += 1
                print(
                    f"Updated job {doc_id} (job_id={job_id}) to status 'verified' (replies_count={replies_count_int})",
                    file=sys.stderr,
                )
            except Exception as e:
                analyzed_job["reason"] = f"Error updating: {e}"
                error_count += 1
                print(f"Error updating job {doc_id}: {e}", file=sys.stderr)
        else:
            print(
                f"[DRY RUN] Would update job {doc_id} (job_id={job_id}) to status 'verified' (replies_count={replies_count_int})",
                file=sys.stderr,
            )

        analyzed_jobs.append(analyzed_job)

    # Generate summary statistics
    summary = {
        "total_empty_result_jobs": len(jobs),
        "jobs_verified": verified_count,
        "jobs_updated": updated_count if not dry_run else verified_count,
        "jobs_skipped": skipped_count,
        "jobs_errors": error_count,
        "dry_run": dry_run,
        "platforms": {},
        "countries": {},
    }

    # Calculate platform and country distribution
    for job in analyzed_jobs:
        platform = job.get("platform") or "unknown"
        country = job.get("country") or "unknown"
        summary["platforms"][platform] = summary["platforms"].get(platform, 0) + 1
        summary["countries"][country] = summary["countries"].get(country, 0) + 1

    return {
        "summary": summary,
        "jobs": analyzed_jobs,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    """Main entry point for the script."""
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Verify empty_result jobs and update status to 'verified' for Twitter posts with replies_count <= 2"
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
        "--candidate-id",
        type=str,
        default=None,
        help="Filter jobs by candidate_id",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of jobs to analyze (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't update Firestore, only report what would be updated",
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
        default="json",
        help="Output format: json or text (default: json)",
    )

    args = parser.parse_args()

    # Get configuration from environment or arguments
    project_id = args.project_id or os.getenv("GCP_PROJECT_ID")
    database_name = args.database or os.getenv("FIRESTORE_DATABASE", "socialnetworks")
    jobs_collection = args.jobs_collection or os.getenv("FIRESTORE_JOBS_COLLECTION", "pending_jobs")
    posts_collection = args.posts_collection or os.getenv("FIRESTORE_COLLECTION", "posts")

    if args.dry_run:
        print("Running in DRY RUN mode - no changes will be made to Firestore", file=sys.stderr)

    try:
        # Verify and update empty jobs
        results = verify_and_update_empty_jobs(
            jobs_collection=jobs_collection,
            posts_collection=posts_collection,
            database_name=database_name,
            project_id=project_id,
            candidate_id=args.candidate_id,
            limit=args.limit,
            dry_run=args.dry_run,
        )

        # Format output
        if args.format == "json":
            output = json.dumps(results, ensure_ascii=False, indent=2, default=str)
        else:
            # Text format
            output_lines = []
            output_lines.append("=" * 80)
            output_lines.append("VERIFY EMPTY RESULT JOBS REPORT")
            output_lines.append("=" * 80)
            output_lines.append("")
            output_lines.append(f"Generated at: {results['generated_at']}")
            output_lines.append(f"Dry run: {results['summary']['dry_run']}")
            output_lines.append("")
            output_lines.append("SUMMARY:")
            output_lines.append(
                f"  Total empty_result jobs: {results['summary']['total_empty_result_jobs']}"
            )
            output_lines.append(
                f"  Jobs verified (conditions met): {results['summary']['jobs_verified']}"
            )
            output_lines.append(f"  Jobs updated: {results['summary']['jobs_updated']}")
            output_lines.append(f"  Jobs skipped: {results['summary']['jobs_skipped']}")
            output_lines.append(f"  Jobs with errors: {results['summary']['jobs_errors']}")
            output_lines.append("")
            output_lines.append("=" * 80)
            output_lines.append("DETAILED JOB INFORMATION")
            output_lines.append("=" * 80)
            output_lines.append("")

            for i, job in enumerate(results["jobs"], 1):
                output_lines.append(f"Job #{i}:")
                output_lines.append(f"  Document ID: {job['doc_id']}")
                output_lines.append(f"  Job ID: {job['job_id']}")
                output_lines.append(f"  Post ID: {job['post_id']}")
                output_lines.append(f"  Post Doc ID: {job['post_doc_id']}")
                output_lines.append(f"  Platform: {job['platform']}")
                output_lines.append(f"  Country: {job['country']}")
                output_lines.append(f"  Candidate ID: {job['candidate_id']}")
                if "replies_count" in job:
                    output_lines.append(f"  Replies Count: {job['replies_count']}")
                output_lines.append(f"  Reason: {job['reason']}")
                if job["should_update"]:
                    status = "WOULD BE UPDATED" if results["summary"]["dry_run"] else "UPDATED"
                    output_lines.append(f"  Status: {status} to '{job['new_status']}'")
                output_lines.append("")
                output_lines.append("-" * 80)
                output_lines.append("")

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
        print(f"Error verifying empty jobs: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
