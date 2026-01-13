#!/usr/bin/env python3
"""
Script to identify successful jobs completed today.

Lists all jobs with status='done' that were updated today (based on updated_at timestamp).

Usage:
    # List all successful jobs today
    poetry run python scripts/list_successful_jobs_today.py

    # Export to CSV
    poetry run python scripts/list_successful_jobs_today.py --output-csv jobs_today.csv

    # Filter by candidate
    poetry run python scripts/list_successful_jobs_today.py --candidate-id hnd01monc

    # Filter by platform
    poetry run python scripts/list_successful_jobs_today.py --platform instagram

    # Filter by country
    poetry run python scripts/list_successful_jobs_today.py --country honduras
"""

import argparse
import csv
import os
import sys
from datetime import datetime, timezone
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


def get_today_range() -> tuple[datetime, datetime]:
    """Get start and end of today in UTC."""
    now = datetime.now(timezone.utc)
    start_of_day = datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=timezone.utc)
    end_of_day = datetime(now.year, now.month, now.day, 23, 59, 59, 999999, tzinfo=timezone.utc)
    return start_of_day, end_of_day


def list_successful_jobs_today(
    collection: str = "pending_jobs",
    database: str = "socialnetworks",
    project_id: str | None = None,
    candidate_id: str | None = None,
    platform: str | None = None,
    country: str | None = None,
) -> list[dict[str, Any]]:
    """
    List all successful jobs (status='done') that were updated today.

    Returns:
        List of job documents with their details
    """
    client = get_firestore_client_custom(project_id, database)

    # Get today's date range
    start_of_day, end_of_day = get_today_range()

    # Build query - only filter by status to avoid index requirement
    # We'll filter by date and other fields in Python
    query = client.collection(collection).where("status", "==", "done")

    # Apply optional filters that don't require composite index
    if candidate_id:
        query = query.where("candidate_id", "==", candidate_id)
    if platform:
        query = query.where("platform", "==", platform.lower())
    if country:
        query = query.where("country", "==", country.lower())

    # Fetch all jobs with status='done' (and optional filters)
    # Then filter by date in Python to avoid index requirement
    jobs = []
    for doc in query.stream():
        job_data = doc.to_dict()
        job_data["_doc_id"] = doc.id

        # Filter by updated_at date in Python
        updated_at = job_data.get("updated_at")
        if updated_at is None:
            continue

        # Convert Firestore timestamp to datetime if needed
        if hasattr(updated_at, "timestamp"):
            updated_dt = updated_at
        elif isinstance(updated_at, datetime):
            updated_dt = updated_at
        else:
            continue

        # Check if updated today
        if start_of_day <= updated_dt <= end_of_day:
            jobs.append(job_data)

    # Sort by updated_at descending (most recent first)
    jobs.sort(
        key=lambda x: x.get("updated_at", datetime.min.replace(tzinfo=timezone.utc)),
        reverse=True,
    )

    return jobs


def format_timestamp(ts: Any) -> str:
    """Format a Firestore timestamp to readable string."""
    if ts is None:
        return "N/A"
    if hasattr(ts, "timestamp"):
        # Firestore timestamp
        dt = ts
    elif isinstance(ts, datetime):
        dt = ts
    else:
        return str(ts)

    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def main():
    parser = argparse.ArgumentParser(description="List successful jobs completed today")
    parser.add_argument(
        "--collection",
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
        "--candidate-id",
        type=str,
        default=None,
        help="Filter by candidate_id",
    )
    parser.add_argument(
        "--platform",
        type=str,
        default=None,
        help="Filter by platform (e.g., twitter, instagram)",
    )
    parser.add_argument(
        "--country",
        type=str,
        default=None,
        help="Filter by country",
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

    print("=== Successful Jobs Today ===")
    print(f"Project ID: {project_id or 'from environment'}")
    print(f"Database: {args.database}")
    print(f"Collection: {args.collection}")
    start_of_day, end_of_day = get_today_range()
    print(f"Date range: {start_of_day.strftime('%Y-%m-%d')} (UTC)")
    if args.candidate_id:
        print(f"Filter: candidate_id={args.candidate_id}")
    if args.platform:
        print(f"Filter: platform={args.platform}")
    if args.country:
        print(f"Filter: country={args.country}")
    print()

    try:
        jobs = list_successful_jobs_today(
            collection=args.collection,
            database=args.database,
            project_id=project_id,
            candidate_id=args.candidate_id,
            platform=args.platform,
            country=args.country,
        )

        print(f"Found {len(jobs)} successful jobs today\n")

        if len(jobs) == 0:
            print("No successful jobs found for today.")
            return

        # Prepare data for display/CSV
        jobs_data = []
        for job in jobs:
            job_info = {
                "doc_id": job.get("_doc_id", ""),
                "job_id": job.get("job_id", ""),
                "post_id": job.get("post_id", ""),
                "platform": job.get("platform", ""),
                "country": job.get("country", ""),
                "candidate_id": job.get("candidate_id", ""),
                "status": job.get("status", ""),
                "max_posts": job.get("max_posts", ""),
                "retry_count": job.get("retry_count", 0),
                "created_at": format_timestamp(job.get("created_at")),
                "updated_at": format_timestamp(job.get("updated_at")),
            }
            jobs_data.append(job_info)

        # Display summary
        print("Summary:")
        print("=" * 80)
        platforms = {}
        countries = {}
        candidates = {}
        for job in jobs_data:
            platform = job["platform"]
            country = job["country"]
            candidate = job["candidate_id"]
            platforms[platform] = platforms.get(platform, 0) + 1
            countries[country] = countries.get(country, 0) + 1
            candidates[candidate] = candidates.get(candidate, 0) + 1

        print(f"Total jobs: {len(jobs_data)}")
        print("\nBy platform:")
        for platform, count in sorted(platforms.items()):
            print(f"  {platform}: {count}")
        print("\nBy country:")
        for country, count in sorted(countries.items()):
            print(f"  {country}: {count}")
        print("\nBy candidate:")
        for candidate, count in sorted(candidates.items()):
            print(f"  {candidate}: {count}")

        # Display first 20 jobs
        print("\n" + "=" * 80)
        print("Jobs (showing first 20):")
        print("=" * 80)
        print(
            f"{'Job ID':<20} {'Post ID':<20} {'Platform':<10} {'Country':<10} "
            f"{'Candidate':<12} {'Updated At':<20}"
        )
        print("-" * 80)

        for job in jobs_data[:20]:
            job_id_short = job["job_id"][:17] + "..." if len(job["job_id"]) > 20 else job["job_id"]
            post_id_short = (
                job["post_id"][:17] + "..." if len(job["post_id"]) > 20 else job["post_id"]
            )
            print(
                f"{job_id_short:<20} {post_id_short:<20} {job['platform']:<10} "
                f"{job['country']:<10} {job['candidate_id']:<12} {job['updated_at']:<20}"
            )

        if len(jobs_data) > 20:
            print(f"\n... and {len(jobs_data) - 20} more jobs")

        # Export to CSV if requested
        if args.output_csv:
            csv_path = Path(args.output_csv)
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                if jobs_data:
                    writer = csv.DictWriter(f, fieldnames=jobs_data[0].keys())
                    writer.writeheader()
                    writer.writerows(jobs_data)
            print(f"\nExported {len(jobs_data)} jobs to {csv_path}")

    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
