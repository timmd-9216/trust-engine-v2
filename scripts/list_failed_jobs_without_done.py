#!/usr/bin/env python3
"""
List jobs with status='failed' that do NOT have another job for the same post_id
with status='done'.

Useful to find posts that failed and were never successfully processed (candidates
for create_reprocess_jobs).

Usage:
    poetry run python scripts/list_failed_jobs_without_done.py
    poetry run python scripts/list_failed_jobs_without_done.py --json out.json
    poetry run python scripts/list_failed_jobs_without_done.py --csv out.csv
"""

import argparse
import csv
import json
import os
import sys

try:
    from dotenv import load_dotenv
    from google.cloud import firestore
except ImportError:
    print("Error: Required packages not installed.", file=sys.stderr)
    print("Install with: poetry install", file=sys.stderr)
    sys.exit(1)

load_dotenv()

JOBS_COLLECTION = os.getenv("FIRESTORE_JOBS_COLLECTION", "pending_jobs")
DATABASE = os.getenv("FIRESTORE_DATABASE", "socialnetworks")
PROJECT_ID = os.getenv("GCP_PROJECT_ID")


def has_done_job_for_post(client: firestore.Client, collection: str, post_id: str) -> bool:
    """Return True if there is at least one job with status='done' for this post_id."""
    query = (
        client.collection(collection)
        .where("post_id", "==", post_id)
        .where("status", "==", "done")
        .limit(1)
    )
    return len(list(query.stream())) > 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List failed jobs that have no 'done' job for the same post_id"
    )
    parser.add_argument(
        "--json",
        type=str,
        metavar="PATH",
        help="Write results as JSON (array of job summaries)",
    )
    parser.add_argument(
        "--csv",
        type=str,
        metavar="PATH",
        help="Write results as CSV (post_id, candidate_id, platform, country, job_doc_id)",
    )
    args = parser.parse_args()

    if PROJECT_ID:
        client = firestore.Client(project=PROJECT_ID, database=DATABASE)
    else:
        client = firestore.Client(database=DATABASE)

    print(
        f"Querying jobs with status='failed' in {DATABASE}.{JOBS_COLLECTION}...",
        file=sys.stderr,
    )
    failed_query = client.collection(JOBS_COLLECTION).where("status", "==", "failed")
    failed_docs = list(failed_query.stream())
    print(f"Total failed jobs: {len(failed_docs)}", file=sys.stderr)

    # Filter: keep only failed jobs whose post_id has no job in status 'done'
    results = []
    for doc in failed_docs:
        data = doc.to_dict()
        post_id = data.get("post_id", "")
        if not post_id:
            continue
        if has_done_job_for_post(client, JOBS_COLLECTION, post_id):
            continue
        results.append(
            {
                "post_id": post_id,
                "candidate_id": data.get("candidate_id", ""),
                "platform": data.get("platform", ""),
                "country": data.get("country", ""),
                "job_id": data.get("job_id", ""),
                "job_doc_id": doc.id,
            }
        )

    print(
        f"Failed jobs without a 'done' job for same post: {len(results)}",
        file=sys.stderr,
    )

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
        print(f"Wrote {len(results)} records to {args.json}", file=sys.stderr)
    elif args.csv:
        if not results:
            with open(args.csv, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(
                    f,
                    fieldnames=[
                        "post_id",
                        "candidate_id",
                        "platform",
                        "country",
                        "job_doc_id",
                    ],
                )
                w.writeheader()
        else:
            with open(args.csv, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(
                    f,
                    fieldnames=[
                        "post_id",
                        "candidate_id",
                        "platform",
                        "country",
                        "job_doc_id",
                    ],
                    extrasaction="ignore",
                )
                w.writeheader()
                w.writerows(results)
        print(f"Wrote {len(results)} records to {args.csv}", file=sys.stderr)
    else:
        for r in results:
            print(
                f"post_id={r['post_id']} candidate_id={r['candidate_id']} "
                f"platform={r['platform']} country={r['country']} job_doc_id={r['job_doc_id']}"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
