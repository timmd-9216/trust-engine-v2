#!/usr/bin/env python3
"""Migrate Firestore collections ('posts', 'pending_jobs') to Postgres (Neon).

Preserves the Firestore document ID as the row's primary key (`id`), so
references like jobs.post_doc_id keep pointing to the right post.

Usage:
    python scripts/vercel/migrate_firestore_to_neon.py \
        --project <gcp-project> --database socialnetworks [--limit N] [--dry-run]

Requires DATABASE_URL in the environment.
"""

import argparse
import os
import sys
from pathlib import Path

try:
    from google.cloud import firestore
except ImportError:
    sys.exit(
        "google-cloud-firestore is not installed. "
        "Install the gcp extra: pip install '.[gcp]' o poetry install --extras gcp"
    )

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from trust_api.scrapping_tools import db  # noqa: E402

POSTS_COLLECTION = "posts"
JOBS_COLLECTION = "pending_jobs"


def migrate_collection(fs_client, collection: str, insert_fn, limit: int | None, dry_run: bool):
    query = fs_client.collection(collection)
    docs = query.limit(limit).stream() if limit else query.stream()

    count = 0
    for doc in docs:
        data = doc.to_dict() or {}
        data["id"] = doc.id
        if dry_run:
            print(f"[dry-run] {collection}/{doc.id}: {sorted(data.keys())}")
        else:
            insert_fn(data)
        count += 1
        if count % 100 == 0:
            print(f"{collection}: {count} documents migrated...")

    print(f"{collection}: {count} documents {'would be migrated' if dry_run else 'migrated'}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=os.getenv("GCP_PROJECT_ID"), help="GCP project ID")
    parser.add_argument("--database", default="socialnetworks", help="Firestore database name")
    parser.add_argument("--limit", type=int, default=None, help="Max docs per collection")
    parser.add_argument("--dry-run", action="store_true", help="Print without writing")
    args = parser.parse_args()

    if not args.dry_run and not os.getenv("DATABASE_URL"):
        sys.exit("ERROR: DATABASE_URL is not set")

    client_kwargs = {"database": args.database}
    if args.project:
        client_kwargs["project"] = args.project
    fs_client = firestore.Client(**client_kwargs)

    migrate_collection(fs_client, POSTS_COLLECTION, db.insert_post, args.limit, args.dry_run)
    migrate_collection(fs_client, JOBS_COLLECTION, db.insert_job, args.limit, args.dry_run)


if __name__ == "__main__":
    main()
