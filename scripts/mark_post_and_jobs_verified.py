#!/usr/bin/env python3
"""
Script to mark a specific post and all its associated jobs as verified.

Updates all jobs associated with a post_doc_id to status='verified' and
the post itself to status='done'.

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


def query_jobs_by_post_doc_id(
    collection: str = "pending_jobs",
    database_name: str = "socialnetworks",
    project_id: str | None = None,
    post_doc_id: str = "",
) -> list[dict[str, Any]]:
    """
    Query Firestore for jobs associated with a specific post_doc_id.

    Args:
        collection: Firestore collection name (default: "pending_jobs")
        database_name: Firestore database name (default: "socialnetworks")
        project_id: GCP project ID (if None, uses default from gcloud)
        post_doc_id: Post document ID to filter jobs

    Returns:
        List of job documents with all fields, including '_doc_id' field with Firestore document ID
    """
    client = get_firestore_client(project_id, database_name)
    query = client.collection(collection).where("post_doc_id", "==", post_doc_id)

    jobs = []
    for doc in query.stream():
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


def update_post_status_in_firestore(
    client: firestore.Client,
    posts_collection: str,
    doc_id: str,
    new_status: str,
) -> None:
    """
    Update the status field of a post document in Firestore.

    Args:
        client: Firestore client
        posts_collection: Posts collection name
        doc_id: Post document ID
        new_status: New status value
    """
    doc_ref = client.collection(posts_collection).document(doc_id)
    now = datetime.now(timezone.utc)
    doc_ref.update({"status": new_status, "updated_at": now})


def mark_post_and_jobs_verified(
    post_doc_id: str,
    jobs_collection: str = "pending_jobs",
    posts_collection: str = "posts",
    database_name: str = "socialnetworks",
    project_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Mark a post and all its associated jobs as verified.

    Args:
        post_doc_id: Post document ID
        jobs_collection: Firestore jobs collection name (default: "pending_jobs")
        posts_collection: Firestore posts collection name (default: "posts")
        database_name: Firestore database name (default: "socialnetworks")
        project_id: GCP project ID (if None, uses default from gcloud)
        dry_run: If True, don't update Firestore, only report what would be updated

    Returns:
        Dictionary containing update results and summary statistics
    """
    # Get Firestore client
    firestore_client = get_firestore_client(project_id, database_name)

    # Verify post exists
    print(f"Checking if post {post_doc_id} exists...", file=sys.stderr)
    post_data = get_post_document(firestore_client, posts_collection, post_doc_id)
    if not post_data:
        return {
            "error": f"Post document {post_doc_id} not found",
            "post_updated": False,
            "jobs_updated": 0,
            "jobs": [],
        }

    post_id = post_data.get("post_id", "unknown")
    post_status = post_data.get("status", "unknown")
    print(f"Post found: post_id={post_id}, current_status={post_status}", file=sys.stderr)

    # Query all jobs associated with this post
    print(
        f"Querying Firestore for jobs with post_doc_id='{post_doc_id}' in collection '{jobs_collection}'...",
        file=sys.stderr,
    )
    jobs = query_jobs_by_post_doc_id(jobs_collection, database_name, project_id, post_doc_id)
    print(f"Found {len(jobs)} jobs associated with post {post_doc_id}", file=sys.stderr)

    # Analyze and update each job
    updated_jobs = []
    errors = []

    for job in jobs:
        doc_id = job.get("_doc_id")
        job_id = job.get("job_id", "unknown")
        current_status = job.get("status", "unknown")

        job_info = {
            "doc_id": doc_id,
            "job_id": job_id,
            "current_status": current_status,
            "updated": False,
            "error": None,
        }

        if not dry_run:
            try:
                update_job_status_in_firestore(
                    firestore_client, jobs_collection, doc_id, "verified"
                )
                job_info["updated"] = True
                updated_jobs.append(job_info)
                print(
                    f"Updated job {doc_id} (job_id={job_id}) from '{current_status}' to 'verified'",
                    file=sys.stderr,
                )
            except Exception as e:
                job_info["error"] = str(e)
                errors.append(f"Error updating job {doc_id}: {e}")
                print(f"Error updating job {doc_id}: {e}", file=sys.stderr)
        else:
            updated_jobs.append(job_info)
            print(
                f"[DRY RUN] Would update job {doc_id} (job_id={job_id}) from '{current_status}' to 'verified'",
                file=sys.stderr,
            )

    # Update post status to 'done'
    post_updated = False
    if not dry_run:
        try:
            update_post_status_in_firestore(firestore_client, posts_collection, post_doc_id, "done")
            post_updated = True
            print(
                f"Updated post {post_doc_id} (post_id={post_id}) from '{post_status}' to 'done'",
                file=sys.stderr,
            )
        except Exception as e:
            errors.append(f"Error updating post {post_doc_id}: {e}")
            print(f"Error updating post {post_doc_id}: {e}", file=sys.stderr)
    else:
        print(
            f"[DRY RUN] Would update post {post_doc_id} (post_id={post_id}) from '{post_status}' to 'done'",
            file=sys.stderr,
        )

    return {
        "post_doc_id": post_doc_id,
        "post_id": post_id,
        "post_old_status": post_status,
        "post_updated": post_updated if not dry_run else False,
        "jobs_found": len(jobs),
        "jobs_updated": len(updated_jobs) if not dry_run else len(updated_jobs),
        "jobs": updated_jobs,
        "errors": errors,
        "dry_run": dry_run,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    """Main entry point for the script."""
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Mark a post and all its associated jobs as verified"
    )
    parser.add_argument(
        "post_doc_id",
        type=str,
        help="Post document ID in Firestore",
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
        result = mark_post_and_jobs_verified(
            post_doc_id=args.post_doc_id,
            jobs_collection=jobs_collection,
            posts_collection=posts_collection,
            database_name=database_name,
            project_id=project_id,
            dry_run=args.dry_run,
        )

        # Format output
        if args.format == "json":
            output = json.dumps(result, ensure_ascii=False, indent=2, default=str)
        else:
            # Text format
            output_lines = []
            output_lines.append("=" * 80)
            output_lines.append("MARK POST AND JOBS AS VERIFIED REPORT")
            output_lines.append("=" * 80)
            output_lines.append("")
            output_lines.append(f"Generated at: {result['generated_at']}")
            output_lines.append(f"Dry run: {result['dry_run']}")
            output_lines.append("")
            output_lines.append("POST INFORMATION:")
            output_lines.append(f"  Post Document ID: {result['post_doc_id']}")
            output_lines.append(f"  Post ID: {result['post_id']}")
            output_lines.append(f"  Old Status: {result['post_old_status']}")
            status = (
                "WOULD BE UPDATED"
                if result["dry_run"]
                else ("UPDATED" if result["post_updated"] else "NOT UPDATED")
            )
            output_lines.append(f"  Post Status: {status} to 'done'")
            output_lines.append("")
            output_lines.append("JOBS INFORMATION:")
            output_lines.append(f"  Jobs Found: {result['jobs_found']}")
            output_lines.append(f"  Jobs Updated: {result['jobs_updated']}")
            output_lines.append("")
            if result["jobs"]:
                output_lines.append("DETAILED JOBS:")
                for i, job in enumerate(result["jobs"], 1):
                    output_lines.append(f"  Job #{i}:")
                    output_lines.append(f"    Document ID: {job['doc_id']}")
                    output_lines.append(f"    Job ID: {job['job_id']}")
                    output_lines.append(f"    Old Status: {job['current_status']}")
                    job_status = (
                        "WOULD BE UPDATED"
                        if result["dry_run"]
                        else ("UPDATED" if job["updated"] else "NOT UPDATED")
                    )
                    output_lines.append(f"    Status: {job_status} to 'verified'")
                    if job.get("error"):
                        output_lines.append(f"    Error: {job['error']}")
                    output_lines.append("")
            if result.get("errors"):
                output_lines.append("ERRORS:")
                for error in result["errors"]:
                    output_lines.append(f"  - {error}")
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

        return 0 if not result.get("error") else 1
    except Exception as e:
        print(f"Error marking post and jobs as verified: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
