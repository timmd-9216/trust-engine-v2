#!/usr/bin/env python3
"""
Script to analyze failed jobs and identify root causes.

Analyzes jobs with status='failed' in Firestore and provides insights about:
- Distribution by date, platform, country, candidate
- Retry patterns
- Post associations
- Potential root causes
"""

import os
import sys
from collections import Counter, defaultdict
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


def analyze_failed_jobs(
    collection: str = "pending_jobs",
    database_name: str = "socialnetworks",
    project_id: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """
    Analyze failed jobs and identify patterns.

    Args:
        collection: Firestore collection name (default: "pending_jobs")
        database_name: Firestore database name (default: "socialnetworks")
        project_id: GCP project ID (if None, uses default from gcloud)
        limit: Maximum number of jobs to analyze (None for all)

    Returns:
        Dictionary containing analysis results
    """
    client = get_firestore_client(project_id, database_name)

    # Query failed jobs
    print("Querying Firestore for jobs with status='failed'...", file=sys.stderr)
    query = client.collection(collection).where("status", "==", "failed")

    if limit:
        jobs = list(query.limit(limit).stream())
    else:
        jobs = list(query.stream())

    print(f"Found {len(jobs)} failed jobs", file=sys.stderr)

    # Analyze patterns
    platforms = Counter()
    countries = Counter()
    candidates = Counter()
    retry_counts = Counter()
    date_groups = Counter()
    posts_jobs = defaultdict(list)
    job_ids_set = set()

    for job_doc in jobs:
        job_data = job_doc.to_dict()

        # Basic stats
        platforms[job_data.get("platform", "unknown")] += 1
        countries[job_data.get("country", "unknown")] += 1
        candidates[job_data.get("candidate_id", "unknown")] += 1
        retry_counts[job_data.get("retry_count", 0)] += 1

        # Date analysis
        updated_at = job_data.get("updated_at")
        if updated_at:
            if hasattr(updated_at, "date"):
                date_key = updated_at.date().isoformat()
            else:
                date_key = str(updated_at)[:10]
            date_groups[date_key] += 1

        # Post analysis
        post_id = job_data.get("post_id")
        if post_id:
            posts_jobs[post_id].append(
                {
                    "doc_id": job_doc.id,
                    "job_id": job_data.get("job_id"),
                    "retry_count": job_data.get("retry_count", 0),
                    "updated_at": updated_at,
                }
            )

        # Job ID uniqueness
        job_id = job_data.get("job_id")
        if job_id:
            job_ids_set.add(job_id)

    # Check post statuses
    post_statuses = Counter()
    sample_posts = list(posts_jobs.keys())[:20]
    for post_id in sample_posts:
        for job_info in posts_jobs[post_id]:
            # Get post_doc_id from a job
            job_doc = client.collection(collection).document(job_info["doc_id"]).get()
            if job_doc.exists:
                job_data = job_doc.to_dict()
                post_doc_id = job_data.get("post_doc_id")
                if post_doc_id:
                    try:
                        post_doc = client.collection("posts").document(post_doc_id).get()
                        if post_doc.exists:
                            post_data = post_doc.to_dict()
                            post_statuses[post_data.get("status", "unknown")] += 1
                            break
                    except Exception:
                        pass

    # Identify root causes
    root_causes = []

    # Cause 1: Duplicate jobs for same posts
    posts_with_many_jobs = [
        (pid, len(jobs_list)) for pid, jobs_list in posts_jobs.items() if len(jobs_list) > 5
    ]
    if posts_with_many_jobs:
        root_causes.append(
            {
                "cause": "Duplicate jobs for same posts",
                "description": f"{len(posts_with_many_jobs)} posts have more than 5 failed jobs each",
                "max_jobs_per_post": max(jobs_count for _, jobs_count in posts_with_many_jobs),
                "affected_posts": len(posts_with_many_jobs),
            }
        )

    # Cause 2: Retry failures
    retry_failures = retry_counts.get(1, 0) + retry_counts.get(2, 0) + retry_counts.get(3, 0)
    if retry_failures > len(jobs) * 0.5:
        root_causes.append(
            {
                "cause": "Retry failures",
                "description": f"{retry_failures} jobs failed after retry (retry_count > 0)",
                "percentage": (retry_failures / len(jobs)) * 100,
            }
        )

    # Cause 3: Date concentration
    if date_groups:
        max_date_count = max(date_groups.values())
        max_date = max(date_groups.items(), key=lambda x: x[1])[0]
        if max_date_count > len(jobs) * 0.5:
            root_causes.append(
                {
                    "cause": "Mass failure event",
                    "description": f"{max_date_count} jobs failed on {max_date} ({max_date_count/len(jobs)*100:.1f}% of all failures)",
                    "date": max_date,
                    "count": max_date_count,
                }
            )

    # Cause 4: Job ID uniqueness
    if len(job_ids_set) == len(jobs):
        root_causes.append(
            {
                "cause": "Unique job IDs",
                "description": "All failed jobs have unique Information Tracer job IDs (not duplicates)",
                "implication": "Each failure is a separate Information Tracer job failure",
            }
        )

    return {
        "total_failed_jobs": len(jobs),
        "unique_job_ids": len(job_ids_set),
        "unique_posts": len(posts_jobs),
        "platforms": dict(platforms),
        "countries": dict(countries),
        "top_candidates": dict(candidates.most_common(10)),
        "retry_count_distribution": dict(retry_counts),
        "failures_by_date": dict(date_groups),
        "posts_with_most_failures": [
            {"post_id": pid, "failed_jobs": len(jobs_list)}
            for pid, jobs_list in sorted(posts_jobs.items(), key=lambda x: len(x[1]), reverse=True)[
                :10
            ]
        ],
        "post_statuses_sample": dict(post_statuses),
        "root_causes": root_causes,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    """Main entry point for the script."""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Analyze failed jobs and identify root causes")
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
        help="GCP Project ID (overrides .env file)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of jobs to analyze (default: all)",
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

    try:
        # Analyze failed jobs
        results = analyze_failed_jobs(
            collection=jobs_collection,
            database_name=database_name,
            project_id=project_id,
            limit=args.limit,
        )

        # Format output
        if args.format == "json":
            output = json.dumps(results, ensure_ascii=False, indent=2, default=str)
        else:
            # Text format
            output_lines = []
            output_lines.append("=" * 80)
            output_lines.append("FAILED JOBS ANALYSIS REPORT")
            output_lines.append("=" * 80)
            output_lines.append("")
            output_lines.append(f"Generated at: {results['generated_at']}")
            output_lines.append("")
            output_lines.append("SUMMARY:")
            output_lines.append(f"  Total failed jobs: {results['total_failed_jobs']}")
            output_lines.append(f"  Unique job IDs: {results['unique_job_ids']}")
            output_lines.append(f"  Unique posts affected: {results['unique_posts']}")
            output_lines.append("")
            output_lines.append("ROOT CAUSES IDENTIFIED:")
            for i, cause in enumerate(results["root_causes"], 1):
                output_lines.append(f"  {i}. {cause['cause']}")
                output_lines.append(f"     {cause['description']}")
                if "percentage" in cause:
                    output_lines.append(f"     Percentage: {cause['percentage']:.1f}%")
                if "date" in cause:
                    output_lines.append(f"     Date: {cause['date']}, Count: {cause['count']}")
                output_lines.append("")
            output_lines.append("=" * 80)
            output_lines.append("DISTRIBUTION BY PLATFORM:")
            for platform, count in results["platforms"].items():
                output_lines.append(f"  {platform}: {count}")
            output_lines.append("")
            output_lines.append("DISTRIBUTION BY COUNTRY:")
            for country, count in results["countries"].items():
                output_lines.append(f"  {country}: {count}")
            output_lines.append("")
            output_lines.append("TOP CANDIDATES:")
            for candidate, count in results["top_candidates"].items():
                output_lines.append(f"  {candidate}: {count}")
            output_lines.append("")
            output_lines.append("RETRY COUNT DISTRIBUTION:")
            for retry_count, count in sorted(results["retry_count_distribution"].items()):
                output_lines.append(f"  retry_count={retry_count}: {count} jobs")
            output_lines.append("")
            output_lines.append("FAILURES BY DATE:")
            for date in sorted(results["failures_by_date"].keys()):
                count = results["failures_by_date"][date]
                output_lines.append(f"  {date}: {count} jobs")
            output_lines.append("")
            output_lines.append("POSTS WITH MOST FAILED JOBS:")
            for post_info in results["posts_with_most_failures"]:
                output_lines.append(
                    f"  Post ID: {post_info['post_id']}, Failed jobs: {post_info['failed_jobs']}"
                )
            output_lines.append("")
            output_lines.append("POST STATUSES (sample):")
            for status, count in results["post_statuses_sample"].items():
                output_lines.append(f"  {status}: {count}")

            output = "\n".join(output_lines)

        print(output)
        return 0
    except Exception as e:
        print(f"Error analyzing failed jobs: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
