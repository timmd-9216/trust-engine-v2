#!/usr/bin/env python3
"""
Script to verify the actual status of failed jobs in Information Tracer.

This queries Information Tracer API directly to check if jobs that are marked
as 'failed' in Firestore are actually failed, or if they were temporary issues.

This helps distinguish between:
1. Real failures (job will never complete)
2. Temporary issues (quota/rate limit) - job might be retryable
3. Jobs that actually succeeded but weren't updated in Firestore
"""

import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

try:
    from google.cloud import firestore

    from trust_api.scrapping_tools.information_tracer import check_status
except ImportError as e:
    missing = "google-cloud-firestore" if "firestore" in str(e) else "trust_api"
    print(f"Error: {missing} is not installed.", file=sys.stderr)
    print("Install dependencies with: poetry install", file=sys.stderr)
    sys.exit(1)

load_dotenv()


def get_firestore_client(
    project_id: str | None = None, database_name: str = "socialnetworks"
) -> firestore.Client:
    """Initialize and return Firestore client."""
    if project_id:
        return firestore.Client(project=project_id, database=database_name)
    return firestore.Client(database=database_name)


def verify_jobs_status(
    jobs_collection: str = "pending_jobs",
    database_name: str = "socialnetworks",
    project_id: str | None = None,
    api_key: str | None = None,
    limit: int = 20,
    sample_date: datetime | None = None,
) -> dict:
    """
    Verify the actual status of failed jobs by querying Information Tracer API.

    Args:
        jobs_collection: Firestore jobs collection name
        database_name: Firestore database name
        project_id: GCP project ID
        api_key: Information Tracer API key
        limit: Maximum number of jobs to verify
        sample_date: If provided, sample jobs from this specific date

    Returns:
        Dictionary with verification results
    """
    if not api_key:
        api_key = os.getenv("INFORMATION_TRACER_API_KEY")
        if not api_key:
            raise ValueError("INFORMATION_TRACER_API_KEY not found in environment")

    client = get_firestore_client(project_id, database_name)

    # Query failed jobs
    print("Querying Firestore for jobs with status='failed'...", file=sys.stderr)
    query = client.collection(jobs_collection).where("status", "==", "failed")

    if sample_date:
        # Sample from a specific date (e.g., mass failure date)
        start_date = sample_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = sample_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        query = query.where("updated_at", ">=", start_date).where("updated_at", "<=", end_date)

    failed_jobs = list(query.limit(limit).stream())
    print(f"Found {len(failed_jobs)} failed jobs to verify", file=sys.stderr)

    results = {
        "total_checked": 0,
        "still_failed": 0,
        "now_finished": 0,
        "now_pending": 0,
        "now_processing": 0,
        "api_error": 0,
        "no_job_id": 0,
        "status_details": [],
    }

    for job_doc in failed_jobs:
        job_data = job_doc.to_dict()
        doc_id = job_doc.id
        job_id = job_data.get("job_id")
        post_id = job_data.get("post_id")

        result_entry = {
            "doc_id": doc_id,
            "job_id": job_id,
            "post_id": post_id,
            "firestore_status": "failed",
            "information_tracer_status": None,
            "error": None,
        }

        results["total_checked"] += 1

        if not job_id:
            result_entry["error"] = "No job_id in Firestore document"
            result_entry["information_tracer_status"] = "unknown"
            results["no_job_id"] += 1
            results["status_details"].append(result_entry)
            continue

        try:
            # Query Information Tracer API for current status
            print(f"Checking job_id={job_id} (post_id={post_id})...", file=sys.stderr)
            current_status = check_status(job_id, api_key)

            result_entry["information_tracer_status"] = current_status

            if current_status == "finished":
                results["now_finished"] += 1
                result_entry["error"] = "Job is actually finished! Firestore status is outdated."
            elif current_status == "failed":
                results["still_failed"] += 1
                result_entry["error"] = "Job is confirmed as failed in Information Tracer"
            elif current_status == "pending":
                results["now_pending"] += 1
                result_entry["error"] = "Job is pending - might have been a temporary issue"
            elif current_status == "processing":
                results["now_processing"] += 1
                result_entry["error"] = "Job is processing - might have been a temporary issue"
            elif current_status == "timeout":
                results["still_failed"] += 1
                result_entry["error"] = "Status check timed out - likely still failed"
            else:
                results["still_failed"] += 1
                result_entry["error"] = f"Unknown status: {current_status}"

        except Exception as e:
            result_entry["error"] = f"Error checking status: {str(e)}"
            result_entry["information_tracer_status"] = "api_error"
            results["api_error"] += 1
            print(f"Error checking job_id={job_id}: {e}", file=sys.stderr)

        results["status_details"].append(result_entry)

    return results


def main() -> int:
    """Main entry point."""
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Verify actual status of failed jobs in Information Tracer"
    )
    parser.add_argument(
        "--jobs-collection",
        type=str,
        default="pending_jobs",
        help="Firestore jobs collection name",
    )
    parser.add_argument(
        "--database",
        type=str,
        default="socialnetworks",
        help="Firestore database name",
    )
    parser.add_argument(
        "--project-id",
        type=str,
        default=None,
        help="GCP Project ID",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="Information Tracer API key (default: from env)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of jobs to verify (default: 20)",
    )
    parser.add_argument(
        "--mass-failure-date",
        action="store_true",
        help="Sample from mass failure date (2026-01-08)",
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["json", "text"],
        default="text",
        help="Output format (default: text)",
    )

    args = parser.parse_args()

    sample_date = None
    if args.mass_failure_date:
        sample_date = datetime(2026, 1, 8, tzinfo=timezone.utc)
        print(f"Sampling jobs from mass failure date: {sample_date.date()}", file=sys.stderr)

    try:
        results = verify_jobs_status(
            jobs_collection=args.jobs_collection,
            database_name=args.database,
            project_id=args.project_id,
            api_key=args.api_key,
            limit=args.limit,
            sample_date=sample_date,
        )

        if args.format == "json":
            output = json.dumps(results, ensure_ascii=False, indent=2, default=str)
        else:
            # Text format
            output_lines = []
            output_lines.append("=" * 80)
            output_lines.append("FAILED JOBS STATUS VERIFICATION")
            output_lines.append("=" * 80)
            output_lines.append("")
            output_lines.append(f"Total jobs checked: {results['total_checked']}")
            output_lines.append("")
            output_lines.append("SUMMARY:")
            output_lines.append(
                f"  Still failed: {results['still_failed']} (confirmed real failures)"
            )
            output_lines.append(
                f"  Now finished: {results['now_finished']} (Firestore status outdated!)"
            )
            output_lines.append(
                f"  Now pending: {results['now_pending']} (temporary issue, retryable)"
            )
            output_lines.append(
                f"  Now processing: {results['now_processing']} (temporary issue, retryable)"
            )
            output_lines.append(f"  API errors: {results['api_error']} (could not check)")
            output_lines.append(f"  No job_id: {results['no_job_id']} (invalid job)")
            output_lines.append("")

            # Calculate percentages
            if results["total_checked"] > 0:
                pct_failed = (results["still_failed"] / results["total_checked"]) * 100
                pct_finished = (results["now_finished"] / results["total_checked"]) * 100
                pct_retryable = (
                    (results["now_pending"] + results["now_processing"]) / results["total_checked"]
                ) * 100

                output_lines.append("PERCENTAGES:")
                output_lines.append(f"  Real failures: {pct_failed:.1f}%")
                output_lines.append(f"  Actually finished: {pct_finished:.1f}%")
                output_lines.append(f"  Retryable (pending/processing): {pct_retryable:.1f}%")
                output_lines.append("")

            output_lines.append("=" * 80)
            output_lines.append("DETAILED RESULTS (first 10):")
            output_lines.append("=" * 80)
            output_lines.append("")

            for i, detail in enumerate(results["status_details"][:10], 1):
                output_lines.append(f"{i}. Job ID: {detail['job_id']}")
                output_lines.append(f"   Firestore status: {detail['firestore_status']}")
                output_lines.append(
                    f"   Information Tracer status: {detail['information_tracer_status']}"
                )
                output_lines.append(f"   Post ID: {detail['post_id']}")
                if detail["error"]:
                    output_lines.append(f"   Note: {detail['error']}")
                output_lines.append("")

            if len(results["status_details"]) > 10:
                output_lines.append(f"... and {len(results['status_details']) - 10} more jobs")

            output = "\n".join(output_lines)

        print(output)
        return 0

    except Exception as e:
        print(f"Error verifying jobs: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
