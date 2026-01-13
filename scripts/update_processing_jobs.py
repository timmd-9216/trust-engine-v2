#!/usr/bin/env python3
"""
Script to update POSTS with status='processing' to 'finished' (or another status)
for post_ids listed in a CSV file.

This updates the status of POSTS in Firestore, not jobs.

Usage:
    # Update processing posts to 'finished'
    poetry run python scripts/update_processing_jobs.py \
      --csv data/bq-reprocess-honduras.csv \
      --new-status finished

    # Update processing posts to 'done'
    poetry run python scripts/update_processing_jobs.py \
      --csv data/bq-reprocess-honduras.csv \
      --new-status done

    # Dry run (see what would be updated)
    poetry run python scripts/update_processing_jobs.py \
      --csv data/bq-reprocess-honduras.csv \
      --new-status finished \
      --dry-run
"""

import argparse
import csv
import os
import sys
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


def find_processing_posts(
    client: firestore.Client,
    posts_collection: str,
    post_id: str,
    platform: str | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """
    Find all posts with status='processing' for a given post_id.

    Returns:
        List of tuples (doc_id, post_data)
    """
    query = (
        client.collection(posts_collection)
        .where("post_id", "==", post_id)
        .where("status", "==", "processing")
    )

    if platform:
        query = query.where("platform", "==", platform.lower())

    posts = []
    for doc in query.stream():
        posts.append((doc.id, doc.to_dict()))

    return posts


def update_post_status_custom(
    client: firestore.Client,
    posts_collection: str,
    doc_id: str,
    new_status: str,
    dry_run: bool = False,
) -> bool:
    """
    Update post status in Firestore.

    Returns:
        True if updated, False otherwise
    """
    if dry_run:
        print(f"  [DRY RUN] Would update post {doc_id} to '{new_status}'")
        return True

    try:
        from datetime import datetime, timezone

        doc_ref = client.collection(posts_collection).document(doc_id)
        now = datetime.now(timezone.utc)
        doc_ref.update({"status": new_status, "updated_at": now})
        return True
    except Exception as e:
        print(f"  ERROR updating post {doc_id}: {e}")
        return False


def process_csv_and_update_posts(
    csv_path: str,
    new_status: str = "finished",
    posts_collection: str = "posts",
    database: str = "socialnetworks",
    project_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Process CSV and update processing posts to new_status.

    Returns:
        Dictionary with processing results
    """
    client = get_firestore_client_custom(project_id, database)

    csv_file = Path(csv_path)
    if not csv_file.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    results = {
        "total_in_csv": 0,
        "posts_with_processing_status": 0,
        "posts_found": 0,
        "posts_updated": 0,
        "errors": 0,
        "posts_processed": [],
    }

    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for row in reader:
            results["total_in_csv"] += 1

            post_id = row.get("post_id", "").strip()
            platform = row.get("platform", "").strip() or None
            country = row.get("country", "").strip()
            candidate_id = row.get("candidate_id", "").strip()

            if not post_id:
                continue

            # Find processing posts for this post_id
            processing_posts = find_processing_posts(client, posts_collection, post_id, platform)

            if processing_posts:
                results["posts_with_processing_status"] += 1
                results["posts_found"] += len(processing_posts)

                print(
                    f"  [{results['posts_with_processing_status']}/{results['total_in_csv']}] "
                    f"post_id={post_id}, platform={platform}, "
                    f"found {len(processing_posts)} post(s) with status='processing'"
                )

                # Update each post
                for post_doc_id, post_data in processing_posts:
                    current_status = post_data.get("status", "unknown")
                    print(f"    Post {post_doc_id[:20]}... (status={current_status})")

                    if update_post_status_custom(
                        client, posts_collection, post_doc_id, new_status, dry_run
                    ):
                        results["posts_updated"] += 1
                        print(f"      Updated to '{new_status}'")
                    else:
                        results["errors"] += 1

                results["posts_processed"].append(
                    {
                        "post_id": post_id,
                        "platform": platform,
                        "country": country,
                        "candidate_id": candidate_id,
                        "posts_count": len(processing_posts),
                    }
                )

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Update processing posts to finished/done for post_ids in CSV"
    )
    parser.add_argument(
        "--csv",
        type=str,
        required=True,
        help="CSV file with post_ids (columns: post_id, platform, country, candidate_id)",
    )
    parser.add_argument(
        "--new-status",
        type=str,
        default="finished",
        help="New status to set (default: finished). Common values: finished, done, noreplies",
    )
    parser.add_argument(
        "--posts-collection",
        type=str,
        default="posts",
        help="Firestore posts collection name (default: posts)",
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
        "--dry-run",
        action="store_true",
        help="Show what would be updated without making changes",
    )

    args = parser.parse_args()

    # Get project_id from environment if not provided
    project_id = args.project_id or os.getenv("GCP_PROJECT_ID")

    print("=== Update Processing Posts ===")
    print(f"Project ID: {project_id or 'from environment'}")
    print(f"Database: {args.database}")
    print(f"Posts Collection: {args.posts_collection}")
    print(f"CSV file: {args.csv}")
    print(f"New status: {args.new_status}")
    print(f"Dry run: {args.dry_run}")
    print()

    try:
        results = process_csv_and_update_posts(
            csv_path=args.csv,
            new_status=args.new_status,
            posts_collection=args.posts_collection,
            database=args.database,
            project_id=project_id,
            dry_run=args.dry_run,
        )

        # Print summary
        print("\n" + "=" * 60)
        print("Summary:")
        print("=" * 60)
        print(f"Total posts in CSV: {results['total_in_csv']}")
        print(f"Posts with status='processing': {results['posts_with_processing_status']}")
        print(f"Total processing posts found: {results['posts_found']}")
        print(f"Posts updated: {results['posts_updated']}")
        print(f"Errors: {results['errors']}")

        if results["posts_processed"]:
            print(f"\nPosts processed ({len(results['posts_processed'])}):")
            for post_info in results["posts_processed"][:10]:  # Show first 10
                print(
                    f"  - post_id={post_info['post_id']}, "
                    f"platform={post_info['platform']}, "
                    f"posts={post_info['posts_count']}"
                )
            if len(results["posts_processed"]) > 10:
                print(f"  ... and {len(results['posts_processed']) - 10} more")

        if args.dry_run:
            print("\n[DRY RUN] No changes were made. Run without --dry-run to apply changes.")

    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
