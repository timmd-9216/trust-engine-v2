#!/usr/bin/env python3
"""
Script to check status of all jobs associated with a candidate_id in Firestore.

Shows detailed information about all jobs for a specific candidate including:
- Total count by status
- Statistics by platform, country
- List of jobs with their details
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


def get_firestore_client_custom(
    project_id: str | None = None, database_name: str = "socialnetworks"
) -> firestore.Client:
    """Initialize and return Firestore client with custom project/database."""
    if project_id:
        return firestore.Client(project=project_id, database=database_name)
    return firestore.Client(database=database_name)


def query_all_jobs_by_candidate(
    collection: str = "pending_jobs",
    database: str = "socialnetworks",
    project_id: str | None = None,
    candidate_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Query Firestore for all jobs associated with a candidate_id (any status).

    Args:
        collection: Firestore jobs collection name
        database: Firestore database name
        project_id: GCP project ID
        candidate_id: Candidate ID to filter jobs

    Returns:
        List of job documents with details
    """
    if not candidate_id:
        raise ValueError("candidate_id is required")

    client = get_firestore_client_custom(project_id, database)

    print(
        f"Querying Firestore for all jobs with candidate_id='{candidate_id}'...",
        file=sys.stderr,
    )

    # Query by candidate_id only (no status filter)
    query = client.collection(collection).where("candidate_id", "==", candidate_id)

    jobs = []
    for doc in query.stream():
        job_data = doc.to_dict()
        job_data["_doc_id"] = doc.id
        jobs.append(job_data)

    # Sort by updated_at descending (most recent first)
    jobs.sort(
        key=lambda x: x.get("updated_at", datetime.min.replace(tzinfo=timezone.utc)),
        reverse=True,
    )

    print(f"Found {len(jobs)} jobs for candidate_id='{candidate_id}'", file=sys.stderr)

    return jobs


def format_timestamp(ts: Any) -> str:
    """Format a Firestore timestamp to readable string."""
    if ts is None:
        return "N/A"
    if hasattr(ts, "timestamp"):
        dt = ts
    elif isinstance(ts, datetime):
        dt = ts
    else:
        return str(ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def generate_statistics(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    """Generate statistics from jobs list."""
    statuses = Counter()
    platforms = Counter()
    countries = Counter()
    retry_counts = Counter()
    hours_by_status = defaultdict(Counter)

    for job in jobs:
        status = job.get("status", "unknown")
        statuses[status] += 1
        platforms[job.get("platform", "unknown")] += 1
        countries[job.get("country", "unknown")] += 1
        retry_counts[job.get("retry_count", 0)] += 1

        # Group by hour and status
        updated_at = job.get("updated_at")
        if updated_at:
            if hasattr(updated_at, "hour"):
                hour_str = f"{updated_at.hour:02d}:00"
            elif isinstance(updated_at, datetime):
                hour_str = f"{updated_at.hour:02d}:00"
            else:
                hour_str = "unknown"
            hours_by_status[status][hour_str] += 1

    return {
        "total": len(jobs),
        "statuses": dict(statuses),
        "platforms": dict(platforms),
        "countries": dict(countries),
        "retry_counts": dict(retry_counts),
        "hours_by_status": {k: dict(v) for k, v in hours_by_status.items()},
    }


def main() -> int:
    """Main entry point for the script."""
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Check status of all jobs for a candidate_id",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check all jobs for a candidate
  poetry run python scripts/check_candidate_jobs_status.py --candidate-id hnd15lope

  # Output as JSON
  poetry run python scripts/check_candidate_jobs_status.py --candidate-id hnd15lope --format json

  # Show only summary
  poetry run python scripts/check_candidate_jobs_status.py --candidate-id hnd15lope --summary-only
        """,
    )
    parser.add_argument(
        "--candidate-id",
        type=str,
        required=True,
        help="Candidate ID to filter jobs",
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
        help="GCP Project ID (overrides .env file)",
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["text", "json"],
        default="text",
        help="Output format: text or json (default: text)",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Show only summary statistics, not detailed job list",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of jobs to display in detailed view (default: all)",
    )

    args = parser.parse_args()

    # Get configuration from environment or arguments
    project_id = args.project_id or os.getenv("GCP_PROJECT_ID")
    database_name = args.database or os.getenv("FIRESTORE_DATABASE", "socialnetworks")
    jobs_collection = args.jobs_collection or os.getenv("FIRESTORE_JOBS_COLLECTION", "pending_jobs")

    try:
        # Get all jobs for candidate
        jobs = query_all_jobs_by_candidate(
            collection=jobs_collection,
            database=database_name,
            project_id=project_id,
            candidate_id=args.candidate_id,
        )

        # Generate statistics
        stats = generate_statistics(jobs)

        # Format output
        if args.format == "json":
            output = json.dumps(
                {"statistics": stats, "jobs": jobs if not args.summary_only else []},
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        else:
            # Text format
            output_lines = []
            output_lines.append("=" * 80)
            output_lines.append(f"JOBS STATUS REPORT - candidate_id: {args.candidate_id}")
            output_lines.append("=" * 80)
            output_lines.append("")

            output_lines.append("SUMMARY:")
            output_lines.append(f"  Total jobs: {stats['total']}")
            output_lines.append("")

            if stats["total"] > 0:
                output_lines.append("STATUS BREAKDOWN:")
                for status, count in sorted(stats["statuses"].items()):
                    percentage = (count / stats["total"]) * 100
                    output_lines.append(f"  {status}: {count} ({percentage:.1f}%)")
                output_lines.append("")

                output_lines.append("PLATFORM BREAKDOWN:")
                for platform, count in sorted(stats["platforms"].items()):
                    output_lines.append(f"  {platform}: {count}")
                output_lines.append("")

                output_lines.append("COUNTRY BREAKDOWN:")
                for country, count in sorted(stats["countries"].items()):
                    output_lines.append(f"  {country}: {count}")
                output_lines.append("")

                if stats["retry_counts"]:
                    output_lines.append("RETRY COUNT DISTRIBUTION:")
                    for retry_count, count in sorted(stats["retry_counts"].items()):
                        output_lines.append(f"  retry_count={retry_count}: {count} jobs")
                    output_lines.append("")

                if not args.summary_only:
                    output_lines.append("DETAILED JOB LIST:")
                    output_lines.append("")

                    # Group jobs by status for better readability
                    jobs_by_status = defaultdict(list)
                    for job in jobs:
                        status = job.get("status", "unknown")
                        jobs_by_status[status].append(job)

                    displayed = 0
                    limit = args.limit if args.limit else len(jobs)

                    for status in sorted(jobs_by_status.keys()):
                        status_jobs = jobs_by_status[status]
                        output_lines.append(f"  Status: {status} ({len(status_jobs)} jobs)")
                        output_lines.append("")

                        for i, job in enumerate(status_jobs[:limit], 1):
                            if displayed >= limit:
                                break
                            output_lines.append(
                                f"    {displayed + 1}. Job ID: {job.get('job_id', 'N/A')}"
                            )
                            output_lines.append(f"       Post ID: {job.get('post_id', 'N/A')}")
                            output_lines.append(f"       Platform: {job.get('platform', 'N/A')}")
                            output_lines.append(f"       Country: {job.get('country', 'N/A')}")
                            output_lines.append(f"       Retry Count: {job.get('retry_count', 0)}")
                            output_lines.append(
                                f"       Created At: {format_timestamp(job.get('created_at'))}"
                            )
                            output_lines.append(
                                f"       Updated At: {format_timestamp(job.get('updated_at'))}"
                            )
                            if job.get("error_message"):
                                error_msg = job.get("error_message", "")[:100]
                                output_lines.append(f"       Error: {error_msg}")
                            output_lines.append("")
                            displayed += 1

                        if displayed >= limit:
                            break

                    if len(jobs) > displayed:
                        output_lines.append(
                            f"  ... and {len(jobs) - displayed} more jobs (use --limit to see more)"
                        )
                        output_lines.append("")
            else:
                output_lines.append("  No jobs found for this candidate_id.")
                output_lines.append("")

            output_lines.append("=" * 80)

            output = "\n".join(output_lines)

        print(output)
        return 0
    except Exception as e:
        print(f"Error checking jobs status: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
