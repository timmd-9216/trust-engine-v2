#!/usr/bin/env python3
"""
Script to analyze failed jobs and update their status based on error logs.

Queries Firestore for jobs with status='failed', searches related error logs in GCS,
and updates the job status to 'empty_result' if the error was due to empty results.

The script reads configuration from .env file or environment variables:
    GCP_PROJECT_ID: GCP project ID
    GCS_BUCKET_NAME: GCS bucket name where logs are stored
    FIRESTORE_DATABASE: Firestore database name (default: socialnetworks)
    FIRESTORE_JOBS_COLLECTION: Firestore jobs collection name (default: pending_jobs)
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

try:
    from dotenv import load_dotenv
    from google.cloud import firestore, storage
except ImportError as e:
    missing = "dotenv" if "dotenv" in str(e) else "google-cloud-firestore"
    if missing == "dotenv":
        print("Error: python-dotenv is not installed.")
        print("Install it with: poetry add python-dotenv")
    else:
        print("Error: google-cloud-firestore or google-cloud-storage is not installed.")
        print("Install it with: poetry add google-cloud-firestore google-cloud-storage")
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


def get_gcs_client(project_id: str | None = None) -> storage.Client:
    """Initialize and return GCS client."""
    if project_id:
        return storage.Client(project=project_id)
    return storage.Client()


def query_failed_jobs(
    collection: str = "pending_jobs",
    database_name: str = "socialnetworks",
    project_id: str | None = None,
    candidate_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """
    Query Firestore for jobs with status='failed'.

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
    query = client.collection(collection).where("status", "==", "failed").order_by("updated_at")

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


def parse_timestamp(timestamp: Any) -> datetime | None:
    """
    Parse a Firestore timestamp to a datetime object.

    Args:
        timestamp: Firestore timestamp or datetime object

    Returns:
        datetime object in UTC, or None if parsing fails
    """
    if timestamp is None:
        return None

    if isinstance(timestamp, datetime):
        return timestamp

    if hasattr(timestamp, "timestamp"):  # Firestore timestamp
        return timestamp

    return None


def format_date_for_gcs(dt: datetime | None) -> str | None:
    """
    Format a datetime object to the date format used in GCS logs (YYYY-MM-DD).

    Args:
        dt: datetime object

    Returns:
        Date string in format YYYY-MM-DD, or None if dt is None
    """
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d")


def search_error_logs_for_job(
    bucket: storage.Bucket,
    job_id: str,
    date_str: str,
) -> dict[str, Any] | None:
    """
    Search for error logs in GCS for a specific job_id and date.

    Searches error logs (logs/errors/YYYY-MM-DD/) for entries matching the job_id.

    Args:
        bucket: GCS bucket object
        job_id: Job ID to search for
        date_str: Date string in format YYYY-MM-DD

    Returns:
        Error entry dict if found, None otherwise
    """
    error_prefix = f"logs/errors/{date_str}/"
    for blob in bucket.list_blobs(prefix=error_prefix):
        if blob.name.endswith(".json"):
            try:
                log_data = json.loads(blob.download_as_text())
                errors = log_data.get("errors", [])
                for error in errors:
                    if error.get("job_id") == job_id:
                        return error
            except Exception as e:
                # Skip logs that can't be parsed
                print(
                    f"Warning: Could not parse error log file {blob.name}: {e}",
                    file=sys.stderr,
                )

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


def analyze_and_update_failed_jobs(
    collection: str = "pending_jobs",
    database_name: str = "socialnetworks",
    bucket_name: str = "",
    project_id: str | None = None,
    candidate_id: str | None = None,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Analyze failed jobs and update their status based on error logs.

    Args:
        collection: Firestore collection name (default: "pending_jobs")
        database_name: Firestore database name (default: "socialnetworks")
        bucket_name: GCS bucket name where logs are stored
        project_id: GCP project ID (if None, uses default from gcloud)
        candidate_id: Optional candidate_id to filter jobs
        limit: Maximum number of failed jobs to analyze (None for all)
        dry_run: If True, don't update Firestore, only report what would be updated

    Returns:
        Dictionary containing analysis results with jobs and summary statistics
    """
    # Query failed jobs
    print(
        f"Querying Firestore for failed jobs in collection '{collection}'...",
        file=sys.stderr,
    )
    if candidate_id:
        print(f"Filtering by candidate_id: {candidate_id}", file=sys.stderr)
    jobs = query_failed_jobs(collection, database_name, project_id, candidate_id, limit)
    print(f"Found {len(jobs)} failed jobs", file=sys.stderr)

    # Get GCS client if bucket is provided
    gcs_client = None
    bucket = None
    if bucket_name:
        print(f"Connecting to GCS bucket '{bucket_name}'...", file=sys.stderr)
        gcs_client = get_gcs_client(project_id)
        bucket = gcs_client.bucket(bucket_name)
    else:
        print("Warning: GCS_BUCKET_NAME not provided. Cannot search error logs.", file=sys.stderr)

    # Get Firestore client for updates
    firestore_client = get_firestore_client(project_id, database_name)

    # Analyze each job
    analyzed_jobs = []
    updated_count = 0
    not_found_count = 0
    empty_result_count = 0

    for job in jobs:
        job_id = job.get("job_id")
        doc_id = job.get("_doc_id")
        post_id = job.get("post_id")
        created_at = parse_timestamp(job.get("created_at"))
        updated_at = parse_timestamp(job.get("updated_at"))

        # Search for error logs
        error_entry = None
        if bucket and job_id:
            # Search logs based on updated_at date (when the job failed)
            search_date = format_date_for_gcs(updated_at) or format_date_for_gcs(created_at)
            if search_date:
                error_entry = search_error_logs_for_job(bucket, job_id, search_date)

        analyzed_job = {
            "doc_id": doc_id,
            "job_id": job_id,
            "post_id": post_id,
            "post_doc_id": job.get("post_doc_id"),
            "platform": job.get("platform"),
            "country": job.get("country"),
            "candidate_id": job.get("candidate_id"),
            "created_at": created_at.isoformat() if created_at else None,
            "updated_at": updated_at.isoformat() if updated_at else None,
            "error_found": error_entry is not None,
            "error_type": error_entry.get("error_type") if error_entry else None,
            "error_message": error_entry.get("error_message") if error_entry else None,
            "should_update": False,
            "new_status": None,
            "updated": False,
        }

        # Check if error is empty_result
        if error_entry and error_entry.get("error_type") == "empty_result":
            analyzed_job["should_update"] = True
            analyzed_job["new_status"] = "empty_result"
            empty_result_count += 1

            if not dry_run:
                try:
                    update_job_status_in_firestore(
                        firestore_client, collection, doc_id, "empty_result"
                    )
                    analyzed_job["updated"] = True
                    updated_count += 1
                    print(
                        f"Updated job {doc_id} (job_id={job_id}) to status 'empty_result'",
                        file=sys.stderr,
                    )
                except Exception as e:
                    print(
                        f"Error updating job {doc_id}: {e}",
                        file=sys.stderr,
                    )
            else:
                print(
                    f"[DRY RUN] Would update job {doc_id} (job_id={job_id}) to status 'empty_result'",
                    file=sys.stderr,
                )
        elif not error_entry:
            not_found_count += 1

        analyzed_jobs.append(analyzed_job)

    # Generate summary statistics
    summary = {
        "total_failed_jobs": len(jobs),
        "jobs_with_error_logs": sum(1 for job in analyzed_jobs if job["error_found"]),
        "jobs_without_error_logs": not_found_count,
        "jobs_with_empty_result": empty_result_count,
        "jobs_updated": updated_count if not dry_run else empty_result_count,
        "dry_run": dry_run,
        "platforms": {},
        "countries": {},
        "date_range": {
            "earliest": None,
            "latest": None,
        },
    }

    # Calculate platform and country distribution
    for job in analyzed_jobs:
        platform = job.get("platform") or "unknown"
        country = job.get("country") or "unknown"
        summary["platforms"][platform] = summary["platforms"].get(platform, 0) + 1
        summary["countries"][country] = summary["countries"].get(country, 0) + 1

    # Calculate date range
    dates = [job["updated_at"] for job in analyzed_jobs if job.get("updated_at")] + [
        job["created_at"] for job in analyzed_jobs if job.get("created_at")
    ]
    if dates:
        summary["date_range"]["earliest"] = min(dates)
        summary["date_range"]["latest"] = max(dates)

    return {
        "summary": summary,
        "jobs": analyzed_jobs,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    """Main entry point for the script."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Analyze failed jobs and update status based on error logs from GCS"
    )
    parser.add_argument(
        "--collection",
        type=str,
        default="pending_jobs",
        help="Firestore collection name (default: pending_jobs)",
    )
    parser.add_argument(
        "--database",
        type=str,
        default="socialnetworks",
        help="Firestore database name (default: socialnetworks)",
    )
    parser.add_argument(
        "--bucket",
        type=str,
        default=None,
        help="GCS bucket name for logs (default: from GCS_BUCKET_NAME env var)",
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
        help="Maximum number of failed jobs to analyze (default: all)",
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
    bucket_name = args.bucket or os.getenv("GCS_BUCKET_NAME", "")
    database_name = args.database or os.getenv("FIRESTORE_DATABASE", "socialnetworks")
    collection = args.collection or os.getenv("FIRESTORE_JOBS_COLLECTION", "pending_jobs")

    if not bucket_name:
        print(
            "Warning: GCS_BUCKET_NAME not provided. Cannot search error logs.",
            file=sys.stderr,
        )

    if args.dry_run:
        print("Running in DRY RUN mode - no changes will be made to Firestore", file=sys.stderr)

    try:
        # Analyze and update failed jobs
        results = analyze_and_update_failed_jobs(
            collection=collection,
            database_name=database_name,
            bucket_name=bucket_name,
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
            output_lines.append("FAILED JOBS ANALYSIS REPORT")
            output_lines.append("=" * 80)
            output_lines.append("")
            output_lines.append(f"Generated at: {results['generated_at']}")
            output_lines.append(f"Dry run: {results['summary']['dry_run']}")
            output_lines.append("")
            output_lines.append("SUMMARY:")
            output_lines.append(f"  Total failed jobs: {results['summary']['total_failed_jobs']}")
            output_lines.append(
                f"  Jobs with error logs: {results['summary']['jobs_with_error_logs']}"
            )
            output_lines.append(
                f"  Jobs without error logs: {results['summary']['jobs_without_error_logs']}"
            )
            output_lines.append(
                f"  Jobs with empty_result error: {results['summary']['jobs_with_empty_result']}"
            )
            output_lines.append(f"  Jobs updated: {results['summary']['jobs_updated']}")
            output_lines.append("")
            output_lines.append("Platform distribution:")
            for platform, count in sorted(
                results["summary"]["platforms"].items(), key=lambda x: x[1], reverse=True
            ):
                output_lines.append(f"  {platform}: {count}")
            output_lines.append("")
            output_lines.append("Country distribution:")
            for country, count in sorted(
                results["summary"]["countries"].items(), key=lambda x: x[1], reverse=True
            ):
                output_lines.append(f"  {country}: {count}")
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
                output_lines.append(f"  Created at: {job['created_at']}")
                output_lines.append(f"  Updated at: {job['updated_at']}")
                output_lines.append(f"  Error found in logs: {job['error_found']}")
                if job["error_found"]:
                    output_lines.append(f"  Error type: {job['error_type']}")
                    output_lines.append(f"  Error message: {job['error_message']}")
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
        print(f"Error analyzing failed jobs: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
