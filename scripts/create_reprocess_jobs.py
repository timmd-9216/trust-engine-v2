#!/usr/bin/env python3
"""
Script to create reprocess jobs for posts from a CSV file or a JSON file (execution log).

Input:
- CSV: post_id, candidate_id, replies_count (optional; from post/job in Firestore if empty)
- JSON: object with "errors" (e.g. process-jobs execution log) or array of error objects.
  By default only entries with error_type "failed" are reprocessed (use --error-type to change).

For each post:
1. Find the post in Firestore by post_id (and platform/country from input or args)
2. Update post status to 'noreplies' to allow reprocessing
3. Optionally delete existing jobs (--delete-existing)
4. Create a new job by submitting to Information Tracer API
5. Save the job to pending_jobs collection

Usage:
    poetry run python scripts/create_reprocess_jobs.py --csv /path/to/posts.csv
    poetry run python scripts/create_reprocess_jobs.py --json /path/to/process-jobs-errors.json
"""

import argparse
import csv
import json
import os
import sys
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:
    missing = "dotenv"
    if missing == "dotenv":
        print("Error: python-dotenv is not installed.", file=sys.stderr)
        print("Install it with: poetry add python-dotenv", file=sys.stderr)
    else:
        print("Error: google-cloud-firestore is not installed.", file=sys.stderr)
        print("Install it with: poetry add google-cloud-firestore", file=sys.stderr)
    sys.exit(1)

# Add src to path to import from trust_api
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from trust_api.scrapping_tools.core.config import settings
from trust_api.scrapping_tools.services import (
    get_firestore_client,
    has_existing_job_for_post,
    save_pending_job,
    submit_post_job,
    update_post_status,
)

# Load environment variables from .env file
load_dotenv()


def find_post_by_post_id(
    post_id: str,
    platform: str | None = None,
    country: str | None = None,
    posts_collection: str | None = None,
) -> tuple[str | None, dict[str, Any] | None]:
    """
    Find a post in Firestore by post_id.

    Args:
        post_id: The post ID to search for
        platform: Optional platform filter (e.g., 'instagram')
        country: Optional country filter (e.g., 'honduras')
        posts_collection: Posts collection name (default: from settings)

    Returns:
        Tuple of (doc_id, post_data) or (None, None) if not found
    """
    client = get_firestore_client()
    collection_name = posts_collection or settings.firestore_collection

    # Query by post_id
    query = client.collection(collection_name).where("post_id", "==", post_id)

    # Add optional filters
    if platform:
        query = query.where("platform", "==", platform)
    if country:
        query = query.where("country", "==", country)

    # Execute query
    docs = list(query.stream())

    if not docs:
        return None, None

    if len(docs) > 1:
        print(
            f"Warning: Multiple posts found with post_id={post_id}",
            file=sys.stderr,
        )

    # Return first match
    doc = docs[0]
    return doc.id, doc.to_dict()


def has_pending_job_for_post(
    post_id: str,
    jobs_collection: str | None = None,
) -> bool:
    """
    Check if there's already a pending job for a given post_id.

    Args:
        post_id: The post ID to check
        jobs_collection: Jobs collection name (default: from settings)

    Returns:
        True if there's an existing pending job, False otherwise
    """
    client = get_firestore_client()
    collection_name = jobs_collection or settings.firestore_jobs_collection

    # Query jobs by post_id with status pending
    query = (
        client.collection(collection_name)
        .where("post_id", "==", post_id)
        .where("status", "==", "pending")
        .limit(1)
    )
    return len(list(query.stream())) > 0


def delete_jobs_for_post(
    post_id: str,
    jobs_collection: str | None = None,
) -> int:
    """
    Delete all jobs (pending or processing) for a specific post_id.

    Args:
        post_id: The post ID to delete jobs for
        jobs_collection: Jobs collection name (default: from settings)

    Returns:
        Number of jobs deleted
    """
    client = get_firestore_client()
    collection_name = jobs_collection or settings.firestore_jobs_collection

    # Query jobs by post_id with status pending or processing
    query = client.collection(collection_name).where("post_id", "==", post_id)

    deleted_count = 0
    for doc in query.stream():
        job_data = doc.to_dict()
        status = job_data.get("status", "")
        # Only delete pending or processing jobs
        if status in ("pending", "processing"):
            doc.reference.delete()
            deleted_count += 1

    return deleted_count


def get_max_posts_replies_from_job(
    post_id: str,
    jobs_collection: str | None = None,
) -> int | None:
    """
    Get max_posts_replies from an existing job for this post_id (any status).

    Args:
        post_id: The post ID to look up jobs for
        jobs_collection: Jobs collection name (default: from settings)

    Returns:
        max_posts_replies from the first job found, or None
    """
    client = get_firestore_client()
    collection_name = jobs_collection or settings.firestore_jobs_collection
    query = client.collection(collection_name).where("post_id", "==", post_id).limit(1)
    docs = list(query.stream())
    if not docs:
        return None
    job_data = docs[0].to_dict()
    val = job_data.get("max_posts_replies")
    if val is not None and isinstance(val, (int, float)) and val > 0:
        return int(val)
    return None


def load_posts_from_csv(csv_path: str) -> list[dict[str, str]]:
    """
    Load posts from CSV file.

    Expected CSV format:
        post_id,candidate_id,replies_count
        (replies_count optional: resolved from post then job in Firestore, else CSV, else 1)

    Returns:
        List of dictionaries with post data
    """
    posts = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            post_id = row.get("post_id", "").strip()
            if post_id:
                posts.append(
                    {
                        "post_id": post_id,
                        "candidate_id": row.get("candidate_id", "").strip(),
                        "replies_count": row.get("replies_count", "").strip(),
                        "platform": row.get("platform", "").strip() or None,
                        "country": row.get("country", "").strip() or None,
                    }
                )
    return posts


def load_posts_from_json(
    json_path: str,
    error_type_filter: str = "failed",
) -> list[dict[str, Any]]:
    """
    Load posts to reprocess from a JSON file (execution log or array of errors).

    Accepts:
    - Object with "errors" key (e.g. process-jobs execution log): uses errors list
    - Array of error objects: uses the array directly

    Filters to entries where error_type == error_type_filter (default: "failed").
    Deduplicates by post_id (keeps first). platform/country come from each entry.

    Returns:
        List of dicts with post_id, candidate_id, platform, country, replies_count=""
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and "errors" in data:
        items = data["errors"]
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError("JSON must be an object with 'errors' key or an array of error objects")

    filtered = [e for e in items if e.get("error_type") == error_type_filter]
    seen_post_ids: set[str] = set()
    posts = []
    for e in filtered:
        post_id = str(e.get("post_id", "")).strip()
        if not post_id or post_id in seen_post_ids:
            continue
        seen_post_ids.add(post_id)
        posts.append(
            {
                "post_id": post_id,
                "candidate_id": str(e.get("candidate_id", "")).strip(),
                "platform": e.get("platform"),
                "country": e.get("country"),
                "replies_count": "",
            }
        )
    return posts


def create_reprocess_jobs(
    posts: list[dict[str, Any]],
    platform: str = "instagram",
    country: str | None = None,
    delete_existing_jobs: bool = False,
    dry_run: bool = False,
    input_label: str = "input",
) -> dict[str, Any]:
    """
    Create reprocess jobs for posts (from CSV or JSON).

    Args:
        posts: List of post dicts (post_id, candidate_id, optional platform/country/replies_count)
        platform: Default platform when not set per post
        country: Default country when not set per post
        delete_existing_jobs: Whether to delete existing jobs for posts (default: False)
        dry_run: If True, don't create jobs, only report what would be done
        input_label: Label for log line (e.g. "CSV", "JSON")

    Returns:
        Dictionary with processing results
    """
    print(f"Loaded {len(posts)} posts from {input_label}", file=sys.stderr)

    results = {
        "total_posts": len(posts),
        "posts_found": 0,
        "posts_not_found": 0,
        "jobs_created": 0,
        "jobs_failed": 0,
        "jobs_skipped": 0,
        "jobs_deleted": 0,
        "errors": [],
        "jobs_created_details": [],
        "posts_not_found_list": [],
    }

    for post_data in posts:
        post_id = post_data["post_id"]
        candidate_id = post_data["candidate_id"]
        platform_for_post = post_data.get("platform") or platform
        country_for_post = post_data.get("country") or country
        # Find post in Firestore
        doc_id, post_doc = find_post_by_post_id(
            post_id,
            platform=platform_for_post,
            country=country_for_post,
        )

        if not doc_id or not post_doc:
            results["posts_not_found"] += 1
            results["posts_not_found_list"].append(post_id)
            print(f"Post not found: post_id={post_id}", file=sys.stderr)
            continue

        results["posts_found"] += 1
        post_platform = post_doc.get("platform", platform_for_post)
        post_country = post_doc.get("country", country_for_post or "honduras")
        post_candidate_id = post_doc.get("candidate_id", candidate_id)
        current_status = post_doc.get("status", "unknown")
        # max_posts_replies: 1) post in Firestore, 2) existing job in Firestore, 3) CSV, 4) default 1
        max_posts_replies_val = post_doc.get("max_posts_replies")
        if max_posts_replies_val is not None and max_posts_replies_val > 0:
            replies_count = max_posts_replies_val
        else:
            max_posts_replies_val = get_max_posts_replies_from_job(post_id)
            if max_posts_replies_val is not None and max_posts_replies_val > 0:
                replies_count = max_posts_replies_val
                print(
                    f"  Using max_posts_replies={replies_count} from existing job",
                    file=sys.stderr,
                )
            else:
                replies_count_str = post_data.get("replies_count", "").strip()
                replies_count = int(replies_count_str) if replies_count_str.isdigit() else 1

        print(
            f"Processing post_id={post_id}, candidate_id={post_candidate_id}, "
            f"current_status={current_status}",
            file=sys.stderr,
        )

        # Check if there's a pending job (only pending, not processing or other states)
        has_pending_job = has_pending_job_for_post(post_id)

        # Delete existing jobs if requested
        if delete_existing_jobs:
            # Check if there are any jobs to delete (pending or processing)
            has_existing_job = has_existing_job_for_post(post_id)
            if has_existing_job:
                deleted_count = 0
                if not dry_run:
                    deleted_count = delete_jobs_for_post(post_id)
                else:
                    deleted_count = 1  # Assume 1 job exists
                if deleted_count > 0:
                    results["jobs_deleted"] += deleted_count
                    print(
                        f"  Deleted {deleted_count} existing job(s) for post_id={post_id}",
                        file=sys.stderr,
                    )
                    has_pending_job = False  # Reset flag after deletion

        # Skip creating job only if there's a pending job and we're not deleting
        if has_pending_job and not delete_existing_jobs:
            results["jobs_skipped"] += 1
            print(
                f"  Skipped creating job: post_id={post_id} already has a pending job",
                file=sys.stderr,
            )
            continue

        # Update post status to 'noreplies' if not already
        if current_status != "noreplies":
            if not dry_run:
                update_post_status(doc_id, "noreplies")
                print("  Updated post status to 'noreplies'", file=sys.stderr)
            else:
                print("  [DRY RUN] Would update post status to 'noreplies'", file=sys.stderr)

        # Create new job
        try:
            if dry_run:
                print(
                    f"  [DRY RUN] Would create job: post_id={post_id}, "
                    f"platform={post_platform}, max_posts_replies={replies_count}",
                    file=sys.stderr,
                )
                results["jobs_created"] += 1
                results["jobs_created_details"].append(
                    {
                        "post_id": post_id,
                        "job_id": "DRY_RUN",
                        "job_doc_id": "DRY_RUN",
                    }
                )
            else:
                # Submit job to Information Tracer
                job_id = submit_post_job(
                    post_id=post_id,
                    platform=post_platform,
                    max_posts_replies=replies_count,
                    sort_by="time",
                    start_date="2020-01-01",
                    end_date="2027-12-31",
                )

                if job_id:
                    # Save job to pending_jobs collection
                    job_doc_id = save_pending_job(
                        job_id=job_id,
                        post_doc_id=doc_id,
                        post_id=post_id,
                        platform=post_platform,
                        country=post_country,
                        candidate_id=post_candidate_id,
                        max_posts_replies=replies_count,
                        sort_by="time",
                    )

                    results["jobs_created"] += 1
                    results["jobs_created_details"].append(
                        {
                            "post_id": post_id,
                            "job_id": job_id,
                            "job_doc_id": job_doc_id,
                        }
                    )
                    print(
                        f"  Created job: job_id={job_id}, job_doc_id={job_doc_id}",
                        file=sys.stderr,
                    )
                else:
                    results["jobs_failed"] += 1
                    error_msg = f"Failed to submit job for post_id={post_id}"
                    results["errors"].append(error_msg)
                    print(f"  ERROR: {error_msg}", file=sys.stderr)

        except Exception as e:
            results["jobs_failed"] += 1
            error_msg = f"Error creating job for post_id={post_id}: {str(e)}"
            results["errors"].append(error_msg)
            print(f"  ERROR: {error_msg}", file=sys.stderr)

    return results


def main() -> int:
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Create reprocess jobs for posts from CSV or JSON (execution log / errors array)"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--csv",
        type=str,
        metavar="PATH",
        help="Path to CSV (post_id, candidate_id, replies_count optional; from post/job if empty)",
    )
    group.add_argument(
        "--json",
        type=str,
        metavar="PATH",
        help="Path to JSON: object with 'errors' (e.g. process-jobs log) or array of error objects; "
        "only entries with error_type 'failed' are reprocessed unless --error-type is set",
    )
    parser.add_argument(
        "--error-type",
        type=str,
        default="failed",
        help="When using --json, only reprocess entries with this error_type (default: failed)",
    )
    parser.add_argument(
        "--platform",
        type=str,
        default="instagram",
        help="Default platform (CSV) or fallback when missing in JSON (default: instagram)",
    )
    parser.add_argument(
        "--country",
        type=str,
        default=None,
        help="Default country (CSV) or fallback when missing in JSON (e.g. 'honduras')",
    )
    parser.add_argument(
        "--delete-existing",
        action="store_true",
        help="Delete existing jobs for posts before creating new ones (default: skip if job exists)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't create jobs, only report what would be done",
    )

    args = parser.parse_args()

    if args.csv:
        if not os.path.exists(args.csv):
            print(f"Error: CSV file not found: {args.csv}", file=sys.stderr)
            return 1
        posts = load_posts_from_csv(args.csv)
        input_label = "CSV"
    else:
        if not os.path.exists(args.json):
            print(f"Error: JSON file not found: {args.json}", file=sys.stderr)
            return 1
        try:
            posts = load_posts_from_json(args.json, error_type_filter=args.error_type)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        input_label = "JSON"

    if not posts:
        print("No posts to process.", file=sys.stderr)
        return 0

    try:
        results = create_reprocess_jobs(
            posts=posts,
            platform=args.platform,
            country=args.country,
            delete_existing_jobs=args.delete_existing,
            dry_run=args.dry_run,
            input_label=input_label,
        )

        # Print summary
        print("\n" + "=" * 80, file=sys.stderr)
        print("SUMMARY", file=sys.stderr)
        print("=" * 80, file=sys.stderr)
        print(f"Total posts in input: {results['total_posts']}", file=sys.stderr)
        print(f"Posts found in Firestore: {results['posts_found']}", file=sys.stderr)
        print(f"Posts not found: {results['posts_not_found']}", file=sys.stderr)
        print(f"Jobs created: {results['jobs_created']}", file=sys.stderr)
        print(f"Jobs failed: {results['jobs_failed']}", file=sys.stderr)
        print(f"Jobs skipped: {results['jobs_skipped']}", file=sys.stderr)
        print(f"Jobs deleted: {results['jobs_deleted']}", file=sys.stderr)

        if results["posts_not_found_list"]:
            print(f"\nPosts not found ({len(results['posts_not_found_list'])}):", file=sys.stderr)
            for post_id in results["posts_not_found_list"]:
                print(f"  - {post_id}", file=sys.stderr)

        if results["errors"]:
            print(f"\nErrors ({len(results['errors'])}):", file=sys.stderr)
            for error in results["errors"]:
                print(f"  - {error}", file=sys.stderr)

        if args.dry_run:
            print("\n[DRY RUN] No jobs were actually created", file=sys.stderr)

        return 0

    except Exception as e:
        print(f"Error creating reprocess jobs: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
