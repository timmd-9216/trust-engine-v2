#!/usr/bin/env python3
"""
Script to reactivate jobs with error_type='empty_result' from a process-jobs execution log.

Only applies to platform=instagram. For each error with error_type='empty_result' and
platform='instagram', reactivates the job by moving it from 'empty_result' to 'pending'
using retry_job_from_empty_result(job_doc_id).

By default runs in dry-run mode (--no-dry-run to execute changes).

Usage:
    # Dry run (default) - show what would be reactivated
    poetry run python scripts/reactivate_empty_result_jobs_from_log.py errors.json

    # Execute reactivations
    poetry run python scripts/reactivate_empty_result_jobs_from_log.py errors.json --no-dry-run

    # From stdin
    cat errors.json | poetry run python scripts/reactivate_empty_result_jobs_from_log.py -

    # Limit number of jobs to reactivate
    poetry run python scripts/reactivate_empty_result_jobs_from_log.py errors.json --limit 10
"""

import argparse
import json
import os
import sys
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:
    print("Error: python-dotenv is not installed.", file=sys.stderr)
    print("Install it with: poetry add python-dotenv", file=sys.stderr)
    sys.exit(1)

# Add src to path to import trust_api modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

try:
    from trust_api.scrapping_tools.services import retry_job_from_empty_result
except ImportError as e:
    print(f"Error importing modules: {e}", file=sys.stderr)
    print(
        "Make sure you're running from the project root and dependencies are installed.",
        file=sys.stderr,
    )
    sys.exit(1)

load_dotenv()


def load_errors_from_json(json_path: str | None) -> list[dict[str, Any]]:
    """
    Load errors from JSON file or stdin.

    Accepts:
    - Object with "errors" key (e.g. process-jobs execution log)
    - Array of error objects

    Returns:
        List of error objects
    """
    if json_path == "-" or json_path is None:
        data = json.load(sys.stdin)
    else:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

    if isinstance(data, dict) and "errors" in data:
        return data["errors"]
    if isinstance(data, list):
        return data
    raise ValueError("JSON must be an object with 'errors' key or an array of error objects")


def filter_empty_result_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter errors to only those with error_type='empty_result', platform='instagram', and valid job_doc_id."""
    filtered = []
    seen_job_doc_ids: set[str] = set()

    for e in errors:
        if e.get("error_type") != "empty_result":
            continue
        if (e.get("platform") or "").lower() != "instagram":
            continue
        job_doc_id = e.get("job_doc_id", "").strip()
        if not job_doc_id:
            continue
        # Deduplicate by job_doc_id
        if job_doc_id in seen_job_doc_ids:
            continue
        seen_job_doc_ids.add(job_doc_id)
        filtered.append(e)

    return filtered


def reactivate_empty_result_jobs_from_log(
    json_path: str | None = None,
    dry_run: bool = True,
    limit: int | None = None,
) -> dict[str, Any]:
    """
    Reactivate jobs with empty_result from execution log (platform=instagram only).

    Args:
        json_path: Path to JSON file, or "-" for stdin, or None for stdin
        dry_run: If True, don't update Firestore, only report what would be done
        limit: Maximum number of jobs to reactivate (None for all)

    Returns:
        Dictionary with results and summary
    """
    errors = load_errors_from_json(json_path)
    empty_result_errors = filter_empty_result_errors(errors)

    if limit is not None and limit > 0:
        empty_result_errors = empty_result_errors[:limit]

    print(
        f"Found {len(empty_result_errors)} unique empty_result instagram jobs to reactivate",
        file=sys.stderr,
    )

    processed = []
    reactivated_count = 0
    error_count = 0

    for err in empty_result_errors:
        job_doc_id = err["job_doc_id"]
        post_id = err.get("post_id", "?")
        platform = err.get("platform", "?")
        country = err.get("country", "?")
        candidate_id = err.get("candidate_id", "?")

        item = {
            "job_doc_id": job_doc_id,
            "post_id": post_id,
            "platform": platform,
            "country": country,
            "candidate_id": candidate_id,
            "reactivated": False,
            "error": None,
        }

        try:
            if dry_run:
                print(
                    f"[DRY RUN] Would reactivate job {job_doc_id} (post_id={post_id}, "
                    f"{platform}/{country}/{candidate_id})",
                    file=sys.stderr,
                )
                item["reactivated"] = True
                reactivated_count += 1
            else:
                new_retry_count = retry_job_from_empty_result(job_doc_id)
                item["reactivated"] = True
                item["new_retry_count"] = new_retry_count
                reactivated_count += 1
                print(
                    f"✓ Reactivated job {job_doc_id} (post_id={post_id}) -> pending (retry #{new_retry_count})",
                    file=sys.stderr,
                )
        except Exception as e:
            item["error"] = str(e)
            error_count += 1
            print(f"✗ Error reactivating job {job_doc_id}: {e}", file=sys.stderr)

        processed.append(item)

    return {
        "jobs": processed,
        "summary": {
            "total_empty_result_errors": len(empty_result_errors),
            "reactivated": reactivated_count,
            "errors": error_count,
        },
    }


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Reactivate empty_result jobs from process-jobs execution log JSON"
    )
    parser.add_argument(
        "json_file",
        nargs="?",
        default="-",
        help="Path to JSON file with 'errors' (execution log), or '-' for stdin (default)",
    )
    parser.add_argument(
        "--no-dry-run",
        action="store_true",
        help="Execute reactivations (default is dry-run)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of jobs to reactivate (default: all)",
    )

    args = parser.parse_args()

    json_path = None if args.json_file == "-" else args.json_file
    if json_path and json_path != "-" and not os.path.exists(json_path):
        print(f"Error: File not found: {json_path}", file=sys.stderr)
        return 1

    if args.no_dry_run:
        print("=" * 60, file=sys.stderr)
        print("EXECUTING - Changes will be written to Firestore", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
    else:
        print("=" * 60, file=sys.stderr)
        print("DRY RUN - No changes will be made to Firestore", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

    try:
        results = reactivate_empty_result_jobs_from_log(
            json_path=json_path,
            dry_run=not args.no_dry_run,
            limit=args.limit,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print("\n" + "=" * 60, file=sys.stderr)
    print("SUMMARY", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(
        f"Empty_result jobs to reactivate: {results['summary']['total_empty_result_errors']}",
        file=sys.stderr,
    )
    print(f"Reactivated: {results['summary']['reactivated']}", file=sys.stderr)
    print(f"Errors: {results['summary']['errors']}", file=sys.stderr)

    print(json.dumps(results, indent=2, default=str))
    return 1 if results["summary"]["errors"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
