#!/usr/bin/env python3
"""
Script to search for replies in JSON files stored in GCS by post_id.

Searches through all JSON files in the GCS bucket (raw layer) and finds replies
that respond to a specific post_id.

Example:
    poetry run python scripts/search_replies_by_post_id.py 3776855243175861385
    poetry run python scripts/search_replies_by_post_id.py 3776855243175861385 --bucket my-bucket
    poetry run python scripts/search_replies_by_post_id.py 3776855243175861385 --output results.json
"""

import argparse
import json
import os
import sys
from typing import Any

from dotenv import load_dotenv
from google.cloud import storage

load_dotenv()


def search_replies_in_json(
    data: dict[str, Any] | list[Any],
    post_id: str,
    blob_name: str,
) -> list[dict[str, Any]]:
    """
    Search for replies to a specific post_id in a JSON data structure.

    Args:
        data: JSON data (can be dict, list, or dict with 'data' key)
        post_id: Post ID to search for in replies
        blob_name: Name of the blob/file being searched

    Returns:
        List of matching replies with metadata
    """
    matches = []

    # Check if this is the file for the post itself (Instagram: raw/{country}/{platform}/{candidate_id}/{post_id}.json)
    # In that case, all replies in the file are replies to that post
    is_post_file = blob_name.endswith(f"/{post_id}.json")

    # Handle different data structures
    replies_list: list[dict[str, Any]] = []

    if isinstance(data, list):
        replies_list = data
    elif isinstance(data, dict):
        # Check if there's a 'data' key
        if "data" in data:
            if isinstance(data["data"], list):
                replies_list = data["data"]
            else:
                replies_list = [data["data"]]
        else:
            # Treat the dict itself as a single reply
            replies_list = [data]

    # Search through replies
    for idx, reply in enumerate(replies_list):
        if not isinstance(reply, dict):
            continue

        # If this is the post's own file, all replies are matches
        if is_post_file:
            is_match = True
        else:
            # Check different fields that might contain the post_id being replied to
            # Twitter format
            in_reply_to = reply.get("in_reply_to_status_id_str") or reply.get(
                "in_reply_to_status_id"
            )
            # Instagram format
            if not in_reply_to:
                in_reply_to = (
                    reply.get("parent_post_pk")
                    or reply.get("parent_post_id")
                    or reply.get("parent_id")
                    or reply.get("original_post_pk")
                )
            is_match = in_reply_to == post_id

        # Check if this reply is responding to the target post_id
        if is_match:
            match = {
                "blob_name": blob_name,
                "reply_index": idx,
                "reply_id": reply.get("id_str") or reply.get("id") or reply.get("tweet_id"),
                "in_reply_to_status_id_str": in_reply_to if not is_post_file else post_id,
                "created_at": reply.get("created_at"),
                "full_text": reply.get("full_text")
                or reply.get("text", "")[:200],  # First 200 chars
                "user": {
                    "screen_name": reply.get("user", {}).get("screen_name")
                    if isinstance(reply.get("user"), dict)
                    else None,
                    "name": reply.get("user", {}).get("name")
                    if isinstance(reply.get("user"), dict)
                    else None,
                    "id_str": reply.get("user", {}).get("id_str")
                    if isinstance(reply.get("user"), dict)
                    else None,
                },
                "engagement": {
                    "favorite_count": reply.get("favorite_count", 0),
                    "retweet_count": reply.get("retweet_count", 0),
                    "reply_count": reply.get("reply_count", 0),
                },
                "full_reply": reply,  # Include full reply data
            }
            matches.append(match)

    return matches


def search_replies_in_gcs(
    bucket_name: str,
    post_id: str,
    prefix: str = "raw/",
    max_files: int | None = None,
) -> dict[str, Any]:
    """
    Search for replies to a specific post_id across all JSON files in GCS.

    Args:
        bucket_name: GCS bucket name
        post_id: Post ID to search for
        prefix: Prefix to search in (default: "raw/")
        max_files: Maximum number of files to search (None for all)

    Returns:
        Dictionary with search results
    """
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    all_matches: list[dict[str, Any]] = []
    files_searched = 0
    files_with_matches = 0
    errors = []

    # List all JSON files in the bucket
    blobs = bucket.list_blobs(prefix=prefix)
    json_blobs = [blob for blob in blobs if blob.name.endswith(".json")]

    if max_files:
        json_blobs = json_blobs[:max_files]

    print(f"Searching for replies to post_id={post_id}...", file=sys.stderr)
    print(f"Found {len(json_blobs)} JSON files to search", file=sys.stderr)

    for blob in json_blobs:
        try:
            files_searched += 1
            if files_searched % 100 == 0:
                print(f"  Searched {files_searched}/{len(json_blobs)} files...", file=sys.stderr)

            # Download and parse JSON
            content = blob.download_as_text()
            data = json.loads(content)

            # Search for replies
            matches = search_replies_in_json(data, post_id, blob.name)

            if matches:
                files_with_matches += 1
                all_matches.extend(matches)
                print(f"  ✓ Found {len(matches)} reply(ies) in {blob.name}", file=sys.stderr)

        except json.JSONDecodeError as e:
            error_msg = f"Error parsing JSON in {blob.name}: {str(e)}"
            errors.append(error_msg)
            print(f"  ✗ {error_msg}", file=sys.stderr)
        except Exception as e:
            error_msg = f"Error processing {blob.name}: {str(e)}"
            errors.append(error_msg)
            print(f"  ✗ {error_msg}", file=sys.stderr)

    return {
        "post_id": post_id,
        "total_files_searched": files_searched,
        "files_with_matches": files_with_matches,
        "total_matches": len(all_matches),
        "matches": all_matches,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Search for replies to a specific post_id in GCS JSON files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Search for replies to post_id 3776855243175861385
  poetry run python scripts/search_replies_by_post_id.py 3776855243175861385

  # Search with custom bucket
  poetry run python scripts/search_replies_by_post_id.py 3776855243175861385 --bucket my-bucket

  # Save results to file
  poetry run python scripts/search_replies_by_post_id.py 3776855243175861385 --output results.json

  # Limit search to first 100 files (for testing)
  poetry run python scripts/search_replies_by_post_id.py 3776855243175861385 --max-files 100
        """,
    )
    parser.add_argument(
        "post_id",
        type=str,
        help="Post ID to search for (e.g., 3776855243175861385)",
    )
    parser.add_argument(
        "--bucket",
        type=str,
        default=None,
        help="GCS bucket name (default: from GCS_BUCKET_NAME env var)",
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default="raw/",
        help="Prefix to search in GCS (default: raw/)",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Maximum number of files to search (default: all)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output file path for JSON results (default: print to stdout)",
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["json", "text"],
        default="text",
        help="Output format (default: text)",
    )

    args = parser.parse_args()

    # Get bucket name
    bucket_name = args.bucket or os.getenv("GCS_BUCKET_NAME")
    if not bucket_name:
        print(
            "Error: GCS_BUCKET_NAME not found in environment and --bucket not provided",
            file=sys.stderr,
        )
        return 1

    try:
        # Search for replies
        results = search_replies_in_gcs(
            bucket_name=bucket_name,
            post_id=args.post_id,
            prefix=args.prefix,
            max_files=args.max_files,
        )

        # Format output
        if args.format == "json" or args.output:
            output = json.dumps(results, ensure_ascii=False, indent=2, default=str)
        else:
            # Text format
            output_lines = []
            output_lines.append("=" * 80)
            output_lines.append(f"SEARCH RESULTS FOR POST_ID: {args.post_id}")
            output_lines.append("=" * 80)
            output_lines.append("")
            output_lines.append(f"Files searched: {results['total_files_searched']}")
            output_lines.append(f"Files with matches: {results['files_with_matches']}")
            output_lines.append(f"Total replies found: {results['total_matches']}")
            output_lines.append("")

            if results["errors"]:
                output_lines.append(f"Errors: {len(results['errors'])}")
                for error in results["errors"][:10]:  # Show first 10 errors
                    output_lines.append(f"  - {error}")
                if len(results["errors"]) > 10:
                    output_lines.append(f"  ... and {len(results['errors']) - 10} more errors")
                output_lines.append("")

            if results["matches"]:
                output_lines.append("=" * 80)
                output_lines.append("MATCHES:")
                output_lines.append("=" * 80)
                output_lines.append("")

                for i, match in enumerate(results["matches"], 1):
                    output_lines.append(f"{i}. Reply ID: {match['reply_id']}")
                    output_lines.append(f"   File: {match['blob_name']}")
                    output_lines.append(f"   Created at: {match.get('created_at', 'N/A')}")
                    if match.get("user", {}).get("screen_name"):
                        output_lines.append(
                            f"   User: @{match['user']['screen_name']} ({match['user'].get('name', 'N/A')})"
                        )
                    output_lines.append(f"   Text: {match.get('full_text', 'N/A')[:200]}...")
                    output_lines.append(
                        f"   Engagement: {match['engagement']['favorite_count']} likes, "
                        f"{match['engagement']['retweet_count']} retweets"
                    )
                    output_lines.append("")
            else:
                output_lines.append("No replies found for this post_id.")
                output_lines.append("")

            output = "\n".join(output_lines)

        # Write output
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"Results saved to {args.output}", file=sys.stderr)
        else:
            print(output)

        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
