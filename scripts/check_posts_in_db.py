#!/usr/bin/env python3
"""
Check whether the post_ids of a CSV already exist in Firestore (posts collection),
and summarize the jobs associated with them (pending_jobs collection).

Useful before running upload_to_firestore.py to avoid creating duplicate posts,
or to see what state a batch of posts/jobs is in.

Input CSV: any CSV with a 'post_id' column (e.g. the files uploaded with
upload_to_firestore.py). Optional columns platform/candidate_id are only echoed in output.

Usage:
    poetry run python scripts/check_posts_in_db.py data/ownposts_brasil_step4.csv
    poetry run python scripts/check_posts_in_db.py data/file.csv --missing-csv data/missing.csv
    poetry run python scripts/check_posts_in_db.py gs://trust-prd/stg/retrieval-sources/file.csv
"""

import argparse
import csv
import os
import subprocess
import sys
import tempfile
from collections import Counter

try:
    from dotenv import load_dotenv
    from google.cloud import firestore
except ImportError:
    print("Error: Required packages not installed.", file=sys.stderr)
    print("Install with: poetry install", file=sys.stderr)
    sys.exit(1)

load_dotenv()

POSTS_COLLECTION = os.getenv("FIRESTORE_COLLECTION", "posts")
JOBS_COLLECTION = os.getenv("FIRESTORE_JOBS_COLLECTION", "pending_jobs")
DATABASE = os.getenv("FIRESTORE_DATABASE", "socialnetworks").strip()
PROJECT_ID = os.getenv("GCP_PROJECT_ID")


def resolve_csv_path(path: str) -> str:
    """Download gs:// paths to a temp file; return local path otherwise."""
    if not path.startswith("gs://"):
        return path
    tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
    tmp.close()
    print(f"Downloading {path}...", file=sys.stderr)
    subprocess.run(["gsutil", "-q", "cp", path, tmp.name], check=True)
    return tmp.name


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check if CSV post_ids exist in Firestore and summarize their jobs"
    )
    parser.add_argument("csv_path", help="Local path or gs:// URI of a CSV with a post_id column")
    parser.add_argument(
        "--missing-csv",
        metavar="PATH",
        help="Write rows whose post_id is NOT in Firestore to this CSV (same columns as input)",
    )
    parser.add_argument(
        "--no-jobs",
        action="store_true",
        help="Skip the jobs lookup (faster; only checks posts collection)",
    )
    args = parser.parse_args()

    csv_path = resolve_csv_path(args.csv_path)
    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found: {csv_path}", file=sys.stderr)
        return 1

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = [r for r in reader if (r.get("post_id") or "").strip()]

    if "post_id" not in fieldnames:
        print("Error: CSV has no 'post_id' column", file=sys.stderr)
        return 1

    if PROJECT_ID:
        client = firestore.Client(project=PROJECT_ID, database=DATABASE)
    else:
        client = firestore.Client(database=DATABASE)

    unique_ids = {r["post_id"].strip() for r in rows}
    print(
        f"CSV rows: {len(rows)}; unique post_ids: {len(unique_ids)}; "
        f"db={DATABASE} posts={POSTS_COLLECTION} jobs={JOBS_COLLECTION}",
        file=sys.stderr,
    )

    post_status: Counter = Counter()
    duplicated_in_db: list[str] = []
    missing_rows: list[dict] = []
    job_status: Counter = Counter()
    posts_without_jobs: list[str] = []
    jobs_per_post: Counter = Counter()

    for r in rows:
        post_id = r["post_id"].strip()
        docs = list(client.collection(POSTS_COLLECTION).where("post_id", "==", post_id).stream())
        if not docs:
            missing_rows.append(r)
            continue
        if len(docs) > 1:
            duplicated_in_db.append(post_id)
        for d in docs:
            post_status[d.to_dict().get("status", "<none>")] += 1

        if args.no_jobs:
            continue
        jobs = list(client.collection(JOBS_COLLECTION).where("post_id", "==", post_id).stream())
        if not jobs:
            posts_without_jobs.append(post_id)
        jobs_per_post[len(jobs)] += 1
        for j in jobs:
            job_status[j.to_dict().get("status", "<none>")] += 1

    found_count = len(unique_ids) - len({r["post_id"].strip() for r in missing_rows})
    print(f"\nPOSTS IN DB: {found_count} / {len(unique_ids)}")
    print(f"  status breakdown: {dict(post_status)}")
    if duplicated_in_db:
        print(
            f"  post_ids with >1 doc in DB ({len(duplicated_in_db)}): {sorted(set(duplicated_in_db))}"
        )

    print(f"\nPOSTS NOT IN DB: {len(missing_rows)}")
    for r in missing_rows:
        print(
            f"  post_id={r['post_id']} platform={r.get('platform', '')} "
            f"candidate_id={r.get('candidate_id', '')}"
        )

    if not args.no_jobs:
        print(f"\nJOBS for posts in DB: {sum(job_status.values())}")
        print(f"  status breakdown: {dict(job_status)}")
        print(f"  jobs per post: {dict(sorted(jobs_per_post.items()))}")
        print(f"  posts with NO job: {len(posts_without_jobs)}")
        for post_id in posts_without_jobs:
            print(f"    {post_id}")

    if args.missing_csv:
        with open(args.missing_csv, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(missing_rows)
        print(f"\nWrote {len(missing_rows)} missing rows to {args.missing_csv}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
