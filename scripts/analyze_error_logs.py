#!/usr/bin/env python3
"""
Script to analyze error logs from GCS bucket for a specific date.

Analyzes error logs stored in logs/errors/YYYY-MM-DD/ folder to understand
what happened during a mass failure event (e.g., 2026-01-08).
"""

import json
import os
import sys
from collections import Counter
from typing import Any

try:
    from dotenv import load_dotenv
    from google.cloud import storage
except ImportError as e:
    missing = "dotenv" if "dotenv" in str(e) else "google-cloud-storage"
    if missing == "dotenv":
        print("Error: python-dotenv is not installed.", file=sys.stderr)
        print("Install it with: poetry add python-dotenv", file=sys.stderr)
    else:
        print("Error: google-cloud-storage is not installed.", file=sys.stderr)
        print("Install it with: poetry add google-cloud-storage", file=sys.stderr)
    sys.exit(1)

# Load environment variables from .env file
load_dotenv()


def get_gcs_client(project_id: str | None = None):
    """Initialize and return GCS client."""
    if project_id:
        return storage.Client(project=project_id)
    return storage.Client()


def list_error_logs_for_date(
    bucket_name: str,
    date_str: str,
    project_id: str | None = None,
) -> list[str]:
    """
    List all error log files for a specific date.

    Args:
        bucket_name: GCS bucket name
        date_str: Date in YYYY-MM-DD format
        project_id: GCP project ID (if None, uses default)

    Returns:
        List of blob paths for error logs on that date
    """
    client = get_gcs_client(project_id)
    bucket = client.bucket(bucket_name)

    # List blobs in logs/errors/YYYY-MM-DD/
    prefix = f"logs/errors/{date_str}/"
    blobs = list(bucket.list_blobs(prefix=prefix))

    return [blob.name for blob in blobs if blob.name.endswith(".json")]


def read_error_log(
    bucket_name: str, blob_path: str, project_id: str | None = None
) -> dict[str, Any] | None:
    """
    Read an error log file from GCS.

    Args:
        bucket_name: GCS bucket name
        blob_path: Path to the blob in GCS
        project_id: GCP project ID (if None, uses default)

    Returns:
        Parsed JSON content of the error log, or None if error
    """
    try:
        client = get_gcs_client(project_id)
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_path)

        content = blob.download_as_text()
        return json.loads(content)
    except Exception as e:
        print(f"Error reading {blob_path}: {e}", file=sys.stderr)
        return None


def analyze_error_logs_for_date(
    bucket_name: str,
    date_str: str,
    project_id: str | None = None,
) -> dict[str, Any]:
    """
    Analyze all error logs for a specific date.

    Args:
        bucket_name: GCS bucket name
        date_str: Date in YYYY-MM-DD format
        project_id: GCP project ID (if None, uses default)

    Returns:
        Dictionary containing analysis results
    """
    print(f"Listing error logs for date: {date_str}...", file=sys.stderr)
    blob_paths = list_error_logs_for_date(bucket_name, date_str, project_id)
    print(f"Found {len(blob_paths)} error log files", file=sys.stderr)

    if not blob_paths:
        return {
            "date": date_str,
            "total_log_files": 0,
            "total_errors": 0,
            "error_types": {},
            "api_usage_info": [],
            "sample_errors": [],
            "error_messages": [],
        }

    # Analyze each log file
    all_errors = []
    error_types = Counter()
    execution_types = Counter()
    api_usage_info = []
    error_messages = []

    for blob_path in blob_paths:
        print(f"Reading {blob_path}...", file=sys.stderr)
        log_data = read_error_log(bucket_name, blob_path, project_id)

        if not log_data:
            continue

        # Extract metadata
        execution_type = log_data.get("execution_type", "unknown")
        execution_types[execution_type] += 1

        # Extract API usage information
        api_usage = log_data.get("api_usage")
        if api_usage:
            api_usage_info.append(
                {
                    "log_file": blob_path,
                    "execution_timestamp": log_data.get("execution_timestamp"),
                    "api_usage": api_usage,
                }
            )

        # Extract errors
        errors = log_data.get("errors", [])
        all_errors.extend(errors)

        # Count error types
        for error in errors:
            error_type = error.get("error_type", "unknown")
            error_types[error_type] += 1
            error_message = error.get("error_message", "")
            if error_message:
                error_messages.append(error_message)

    # Get sample errors (first 20)
    sample_errors = all_errors[:20]

    # Analyze error messages for quota/rate limit keywords
    quota_keywords = ["quota", "limit", "rate", "429", "403", "exceeded", "too many"]
    quota_related_errors = []
    for error in all_errors:
        error_msg = str(error.get("error_message", "")).lower()
        if any(keyword in error_msg for keyword in quota_keywords):
            quota_related_errors.append(error)

    return {
        "date": date_str,
        "total_log_files": len(blob_paths),
        "total_errors": len(all_errors),
        "execution_types": dict(execution_types),
        "error_types": dict(error_types),
        "api_usage_info": api_usage_info,
        "sample_errors": sample_errors,
        "quota_related_errors": quota_related_errors[:20],  # First 20
        "error_messages_unique": list(set(error_messages))[:50],  # Unique error messages (first 50)
        "unique_job_ids": len(set(e.get("job_id") for e in all_errors if e.get("job_id"))),
        "unique_post_ids": len(set(e.get("post_id") for e in all_errors if e.get("post_id"))),
    }


def main() -> int:
    """Main entry point for the script."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Analyze error logs from GCS bucket for a specific date"
    )
    parser.add_argument(
        "--bucket",
        type=str,
        default=None,
        help="GCS bucket name (default: from GCS_BUCKET_NAME env var)",
    )
    parser.add_argument(
        "--date",
        type=str,
        required=True,
        help="Date to analyze in YYYY-MM-DD format (e.g., 2026-01-08)",
    )
    parser.add_argument(
        "--project-id",
        type=str,
        default=None,
        help="GCP Project ID (default: from GCP_PROJECT_ID env var)",
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["json", "text"],
        default="text",
        help="Output format: json or text (default: text)",
    )

    args = parser.parse_args()

    # Get configuration
    bucket_name = args.bucket or os.getenv("GCS_BUCKET_NAME")
    if not bucket_name:
        print(
            "Error: GCS bucket name not found. Provide --bucket or set GCS_BUCKET_NAME env var.",
            file=sys.stderr,
        )
        return 1

    project_id = args.project_id or os.getenv("GCP_PROJECT_ID")

    try:
        # Analyze error logs
        results = analyze_error_logs_for_date(
            bucket_name=bucket_name,
            date_str=args.date,
            project_id=project_id,
        )

        # Format output
        if args.format == "json":
            output = json.dumps(results, ensure_ascii=False, indent=2, default=str)
        else:
            # Text format
            output_lines = []
            output_lines.append("=" * 80)
            output_lines.append(f"ERROR LOGS ANALYSIS FOR DATE: {results['date']}")
            output_lines.append("=" * 80)
            output_lines.append("")
            output_lines.append(f"Total log files: {results['total_log_files']}")
            output_lines.append(f"Total errors: {results['total_errors']}")
            output_lines.append(f"Unique job IDs in errors: {results['unique_job_ids']}")
            output_lines.append(f"Unique post IDs in errors: {results['unique_post_ids']}")
            output_lines.append("")

            if results["execution_types"]:
                output_lines.append("EXECUTION TYPES:")
                for exec_type, count in results["execution_types"].items():
                    output_lines.append(f"  {exec_type}: {count} files")
                output_lines.append("")

            if results["error_types"]:
                output_lines.append("ERROR TYPES:")
                for error_type, count in sorted(
                    results["error_types"].items(), key=lambda x: x[1], reverse=True
                ):
                    output_lines.append(f"  {error_type}: {count} errors")
                output_lines.append("")

            if results["api_usage_info"]:
                output_lines.append("API USAGE INFORMATION (from logs):")
                for i, usage_info in enumerate(results["api_usage_info"][:5], 1):  # First 5
                    output_lines.append(f"\n  Log {i} ({usage_info['log_file']}):")
                    output_lines.append(f"    Execution: {usage_info['execution_timestamp']}")
                    api_usage = usage_info["api_usage"]
                    if isinstance(api_usage, dict):
                        if "usage" in api_usage:
                            daily_usage = api_usage["usage"].get("day", {})
                            if "searches_used" in daily_usage:
                                output_lines.append(
                                    f"    Daily searches used: {daily_usage['searches_used']}"
                                )
                            limits = api_usage.get("limits", {})
                            if "max_searches_per_day" in limits:
                                output_lines.append(
                                    f"    Daily limit: {limits['max_searches_per_day']}"
                                )
                        else:
                            output_lines.append(
                                f"    {json.dumps(api_usage, indent=4, default=str)}"
                            )
                    else:
                        output_lines.append(f"    {api_usage}")
                output_lines.append("")

            if results["quota_related_errors"]:
                output_lines.append(
                    f"QUOTA/RATE LIMIT RELATED ERRORS ({len(results['quota_related_errors'])} found):"
                )
                for i, error in enumerate(results["quota_related_errors"][:10], 1):  # First 10
                    output_lines.append(f"\n  Error {i}:")
                    output_lines.append(f"    Type: {error.get('error_type', 'unknown')}")
                    output_lines.append(f"    Message: {error.get('error_message', 'N/A')}")
                    output_lines.append(f"    Job ID: {error.get('job_id', 'N/A')}")
                    output_lines.append(f"    Post ID: {error.get('post_id', 'N/A')}")
                    output_lines.append(f"    Timestamp: {error.get('timestamp', 'N/A')}")
                output_lines.append("")

            if results["error_messages_unique"]:
                output_lines.append("UNIQUE ERROR MESSAGES (first 20):")
                for i, msg in enumerate(results["error_messages_unique"][:20], 1):
                    output_lines.append(f"  {i}. {msg}")
                output_lines.append("")

            if results["sample_errors"]:
                output_lines.append("SAMPLE ERRORS (first 10):")
                for i, error in enumerate(results["sample_errors"][:10], 1):
                    output_lines.append(f"\n  Error {i}:")
                    for key, value in error.items():
                        if key == "error_message" and value:
                            # Truncate long messages
                            msg = str(value)
                            if len(msg) > 200:
                                msg = msg[:200] + "..."
                            output_lines.append(f"    {key}: {msg}")
                        else:
                            output_lines.append(f"    {key}: {value}")
                output_lines.append("")

            output = "\n".join(output_lines)

        print(output)
        return 0

    except Exception as e:
        print(f"Error analyzing error logs: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
