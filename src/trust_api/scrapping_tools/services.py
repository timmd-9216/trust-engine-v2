"""Services for scrapping-tools."""

import json
import time
from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore, storage

from trust_api.scrapping_tools.core.config import settings


def get_firestore_client() -> firestore.Client:
    """Initialize and return Firestore client."""
    if settings.gcp_project_id:
        return firestore.Client(
            project=settings.gcp_project_id, database=settings.firestore_database
        )
    return firestore.Client(database=settings.firestore_database)


def get_gcs_client() -> storage.Client:
    """Initialize and return GCS client."""
    if settings.gcp_project_id:
        return storage.Client(project=settings.gcp_project_id)
    return storage.Client()


def query_posts_without_replies(max_posts: int | None = None) -> list[dict[str, Any]]:
    """
    Query Firestore for posts with status='noreplies'.
    Results are ordered by created_at (oldest first).

    Args:
        max_posts: Maximum number of posts to return. If None, returns all posts.

    Returns:
        List of post documents with fields: post_id, country, platform, candidate_id, etc.
        Each document also includes '_doc_id' field with the Firestore document ID.
    """
    client = get_firestore_client()
    query = (
        client.collection(settings.firestore_collection)
        .where("status", "==", "noreplies")
        .order_by("created_at")  # Order by created_at ascending (oldest first)
    )

    # Apply limit if specified
    if max_posts is not None and max_posts > 0:
        query = query.limit(max_posts)

    posts = []
    for doc in query.stream():
        doc_data = doc.to_dict()
        doc_data["_doc_id"] = doc.id  # Store document ID for later update
        posts.append(doc_data)

    return posts


# Global list to accumulate logs during execution
_execution_logs: list[dict[str, Any]] = []


def reset_execution_logs() -> None:
    """Reset the execution logs list for a new execution."""
    global _execution_logs
    _execution_logs = []


def add_log_entry(
    post_id: str,
    url: str,
    success: bool,
    status_code: int | None = None,
    error_message: str | None = None,
    response_time_ms: float | None = None,
    max_replies: int | None = None,
    skipped: bool = False,
    skip_reason: str | None = None,
    job_id: str | None = None,
) -> None:
    """
    Add a log entry to the execution logs (in-memory).

    Args:
        post_id: The post ID that was queried
        url: The URL that was called
        success: Whether the call was successful
        status_code: HTTP status code (if available)
        error_message: Error message (if call failed)
        response_time_ms: Response time in milliseconds (if available)
        max_replies: Maximum number of replies requested for this post (if available)
        skipped: Whether the post was skipped (not queried)
        skip_reason: Reason for skipping (if skipped)
        job_id: Information Tracer job ID (id_hash256) if available
    """
    now = datetime.now(timezone.utc)
    log_entry = {
        "timestamp": now.isoformat(),
        "post_id": post_id,
        "url": url,
        "success": success,
        "status_code": status_code,
        "error_message": error_message,
        "response_time_ms": response_time_ms,
        "max_replies": max_replies,
        "skipped": skipped,
        "skip_reason": skip_reason,
        "job_id": job_id,
    }
    _execution_logs.append(log_entry)


def save_execution_logs(
    requested_max_posts: int | None = None,
    available_posts: int | None = None,
) -> str | None:
    """
    Save all accumulated execution logs to GCS bucket in logs/ folder.
    Uses a single file per execution.

    Args:
        requested_max_posts: Maximum number of posts requested in the API call (if specified)
        available_posts: Total number of posts available in Firestore with status='noreplies'

    Returns:
        GCS URI of the saved log file, or None if logging fails or is disabled
    """
    if not settings.gcs_bucket_name:
        return None

    if not _execution_logs:
        # No logs to save
        return None

    try:
        client = get_gcs_client()
        bucket = client.bucket(settings.gcs_bucket_name)

        # Create filename: logs/YYYY-MM-DD/HH-MM-SS-{timestamp}.json
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H-%M-%S-%f")[:-3]  # Include milliseconds
        filename = f"{time_str}.json"
        blob_path = f"logs/{date_str}/{filename}"

        # Calculate summary statistics
        total_calls = len(_execution_logs)
        skipped_count = sum(1 for log in _execution_logs if log.get("skipped", False))
        api_calls = total_calls - skipped_count

        # Create log file content with metadata and all entries
        log_file = {
            "execution_timestamp": now.isoformat(),
            "requested_max_posts": requested_max_posts,
            "available_posts": available_posts,
            "total_entries": total_calls,
            "api_calls": api_calls,
            "skipped_posts": skipped_count,
            "calls": _execution_logs,
        }

        blob = bucket.blob(blob_path)
        blob.upload_from_string(
            json.dumps(log_file, ensure_ascii=False, indent=2),
            content_type="application/json",
        )

        return f"gs://{settings.gcs_bucket_name}/{blob_path}"
    except Exception:
        # Silently fail logging to avoid breaking the main flow
        # In production, you might want to log this to a logging service
        return None


def fetch_post_information(
    post_id: str,
    platform: str,
    max_posts: int = 100,
) -> dict[str, Any]:
    """
    Fetch replies for a post using Information Tracer API.
    Logs all calls to GCS bucket in logs/ folder.

    Args:
        post_id: The post ID to get replies for
        platform: The platform where the post is located (twitter, facebook, instagram, etc.)
        max_posts: Maximum number of replies to collect (default: 100)

    Returns:
        Dictionary containing the collected replies from Information Tracer

    Raises:
        ValueError: If INFORMATION_TRACER_API_KEY is not configured or invalid platform
        RuntimeError: If the Information Tracer job fails or times out
    """
    if not settings.information_tracer_api_key:
        raise ValueError("INFORMATION_TRACER_API_KEY is not configured")

    # Import here to avoid circular dependencies
    from trust_api.scrapping_tools.information_tracer import PlatformType, get_post_replies

    # Validate platform type
    valid_platforms: list[PlatformType] = [
        "twitter",
        "facebook",
        "instagram",
        "reddit",
        "youtube",
        "threads",
    ]
    if platform.lower() not in valid_platforms:
        raise ValueError(
            f"Invalid platform: {platform}. Valid platforms are: {', '.join(valid_platforms)}"
        )

    # Track response time
    start_time = time.time()
    error_message = None

    # Construct a descriptive URL for logging purposes
    url = f"https://informationtracer.com/submit (reply:{post_id}, platform:{platform})"

    try:
        # Call Information Tracer API to get replies
        result = get_post_replies(
            post_id=post_id,
            platform=platform.lower(),  # type: ignore
            max_post=max_posts,
            token=settings.information_tracer_api_key,
        )

        # Extract data and job_id from result
        data = result.get("data", result)  # Fallback to result if no "data" key
        job_id = result.get("job_id")

        # Add log entry for successful call (including job_id if available)
        response_time_ms = (time.time() - start_time) * 1000
        add_log_entry(
            post_id=post_id,
            url=url,
            success=True,
            status_code=200,
            response_time_ms=response_time_ms,
            max_replies=max_posts,
            job_id=job_id,
        )

        return data

    except ValueError as e:
        error_message = str(e)
        # Add log entry for failed call
        response_time_ms = (time.time() - start_time) * 1000
        add_log_entry(
            post_id=post_id,
            url=url,
            success=False,
            status_code=None,
            error_message=error_message,
            response_time_ms=response_time_ms,
            max_replies=max_posts,
        )
        raise

    except RuntimeError as e:
        error_message = str(e)
        # Add log entry for failed call
        response_time_ms = (time.time() - start_time) * 1000
        add_log_entry(
            post_id=post_id,
            url=url,
            success=False,
            status_code=None,
            error_message=error_message,
            response_time_ms=response_time_ms,
            max_replies=max_posts,
        )
        raise

    except Exception as e:
        error_message = str(e)
        # Add log entry for failed call
        response_time_ms = (time.time() - start_time) * 1000
        add_log_entry(
            post_id=post_id,
            url=url,
            success=False,
            error_message=error_message,
            response_time_ms=response_time_ms,
            max_replies=max_posts,
        )
        raise


def _get_gcs_blob_path(
    country: str,
    platform: str,
    candidate_id: str,
    post_id: str,
) -> str:
    """
    Generate the GCS blob path for a post.

    Args:
        country: Country name
        platform: Platform name
        candidate_id: Candidate ID
        post_id: Post ID (used for filename)

    Returns:
        Blob path in GCS
    """
    # Normalize path components to avoid issues with special characters
    safe_country = country.replace("/", "_").replace("\\", "_")
    safe_platform = platform.replace("/", "_").replace("\\", "_")
    safe_candidate_id = str(candidate_id).replace("/", "_").replace("\\", "_")
    safe_post_id = str(post_id).replace("/", "_").replace("\\", "_")

    layer_name = "raw"
    return f"{layer_name}/{safe_country}/{safe_platform}/{safe_candidate_id}/{safe_post_id}.json"


def read_from_gcs_if_exists(
    country: str,
    platform: str,
    candidate_id: str,
    post_id: str,
) -> dict[str, Any] | None:
    """
    Read JSON data from GCS bucket if the file exists.

    Args:
        country: Country name
        platform: Platform name
        candidate_id: Candidate ID
        post_id: Post ID (used for filename)

    Returns:
        Dictionary with the JSON data if file exists, None otherwise.
        Returns None if file doesn't exist or if there's an error reading it.

    Raises:
        ValueError: If GCS_BUCKET_NAME is not configured
    """
    if not settings.gcs_bucket_name:
        raise ValueError("GCS_BUCKET_NAME is not configured")

    try:
        client = get_gcs_client()
        bucket = client.bucket(settings.gcs_bucket_name)

        blob_path = _get_gcs_blob_path(country, platform, candidate_id, post_id)
        blob = bucket.blob(blob_path)

        # Check if blob exists
        if blob.exists():
            # Read and parse JSON
            content = blob.download_as_text()
            return json.loads(content)

        return None
    except Exception:
        # If there's any error reading from GCS, return None so we can fall back
        # to fetching from the API. This ensures the process doesn't fail if GCS
        # is temporarily unavailable.
        # Note: We don't log here to avoid breaking the flow, the error will be
        # handled when we try to fetch from the API
        return None


def save_to_gcs(
    data: dict[str, Any],
    country: str,
    platform: str,
    candidate_id: str,
    post_id: str,
) -> str:
    """
    Save JSON data to GCS bucket with structure: country/platform/candidate_id/{post_id}.json

    Args:
        data: JSON data to save
        country: Country name
        platform: Platform name
        candidate_id: Candidate ID
        post_id: Post ID (used for filename)

    Returns:
        GCS URI of the saved file

    Raises:
        ValueError: If GCS_BUCKET_NAME is not configured
    """
    if not settings.gcs_bucket_name:
        raise ValueError("GCS_BUCKET_NAME is not configured")

    client = get_gcs_client()
    bucket = client.bucket(settings.gcs_bucket_name)

    blob_path = _get_gcs_blob_path(country, platform, candidate_id, post_id)

    blob = bucket.blob(blob_path)
    blob.upload_from_string(
        json.dumps(data, ensure_ascii=False, indent=2),
        content_type="application/json",
    )

    return f"gs://{settings.gcs_bucket_name}/{blob_path}"


def update_post_status(doc_id: str, new_status: str = "done") -> None:
    """
    Update the status field of a Firestore document and set updated_at timestamp.

    Args:
        doc_id: The Firestore document ID to update
        new_status: The new status value (default: "done")

    Raises:
        ValueError: If doc_id is not provided
    """
    if not doc_id:
        raise ValueError("doc_id is required to update post status")

    client = get_firestore_client()
    doc_ref = client.collection(settings.firestore_collection).document(doc_id)

    # Get current timestamp in UTC
    now = datetime.now(timezone.utc)

    # Update both status and updated_at
    doc_ref.update(
        {
            "status": new_status,
            "updated_at": now,
        }
    )


def process_posts_service(max_posts: int | None = None) -> dict[str, Any]:
    """
    Main processing function that:
    1. Queries Firestore for posts with status='noreplies'
    2. For each post, queries the external Information Tracer service
    3. Saves the results to GCS
    4. Updates the post status to 'done' in Firestore after successful save
    5. Logs all Information Tracer calls to a single file in GCS

    Args:
        max_posts: Maximum number of posts to process. If None, processes all posts with status='noreplies'.

    Returns:
        Dictionary with processing results including success count, errors, etc.
    """
    # Reset logs for this execution
    reset_execution_logs()

    results = {
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "skipped": 0,
        "errors": [],
        "saved_files": [],
    }

    try:
        # Query all posts without replies to get total count
        all_posts = query_posts_without_replies(max_posts=None)
        available_posts_count = len(all_posts)

        # Apply limit if specified (limit in Python to avoid second query)
        if max_posts is not None and max_posts > 0:
            posts = all_posts[:max_posts]
        else:
            posts = all_posts

        results["processed"] = len(posts)

        for post in posts:
            post_id = post.get("post_id")
            doc_id = post.get("_doc_id")
            if not post_id:
                error_msg = f"Post missing post_id field: {post.get('id', 'unknown')}"
                results["errors"].append(error_msg)
                results["failed"] += 1
                continue

            country = post.get("country", "unknown")
            platform = post.get("platform", "unknown")
            candidate_id = post.get("candidate_id", "unknown")

            try:
                # Fetch replies from Information Tracer service
                # Use max_replies from post if available, otherwise default to 100
                max_replies = post.get("max_replies", 100)

                # Skip posts with no replies expected (max_replies <= 0)
                if max_replies is None or max_replies <= 0:
                    skip_reason = f"max_replies={max_replies} (no replies expected)"
                    add_log_entry(
                        post_id=post_id,
                        url="N/A",
                        success=False,
                        skipped=True,
                        skip_reason=skip_reason,
                        max_replies=max_replies,
                    )
                    results["skipped"] += 1
                    # Update status to "skipped" in Firestore
                    if doc_id:
                        update_post_status(doc_id, "skipped")
                    continue

                # Check if JSON already exists in GCS to avoid duplicate requests
                # WARNING: This check requires a GCS read operation (blob.exists() + download),
                # which is slower than directly calling the API, but prevents duplicate API calls
                # to Information Tracer and saves API quota/costs
                info_data = read_from_gcs_if_exists(
                    country=country,
                    platform=platform,
                    candidate_id=candidate_id,
                    post_id=post_id,
                )

                if info_data is None:
                    # File doesn't exist, fetch from Information Tracer service
                    info_data = fetch_post_information(
                        post_id=post_id,
                        platform=platform,
                        max_posts=max_replies,
                    )

                    # Save to GCS
                    gcs_uri = save_to_gcs(info_data, country, platform, candidate_id, post_id)
                    results["saved_files"].append(gcs_uri)
                else:
                    # File already exists, use existing data
                    # Reconstruct GCS URI for logging
                    blob_path = _get_gcs_blob_path(country, platform, candidate_id, post_id)
                    gcs_uri = f"gs://{settings.gcs_bucket_name}/{blob_path}"
                    results["saved_files"].append(gcs_uri)
                    # Log that we skipped the API call
                    add_log_entry(
                        post_id=post_id,
                        url="N/A (file already exists in GCS)",
                        success=True,
                        skipped=True,
                        skip_reason="File already exists in GCS",
                        max_replies=max_replies,
                    )

                # Update status to "done" in Firestore after successful save
                if doc_id:
                    update_post_status(doc_id, "done")

                results["succeeded"] += 1

            except Exception as e:
                error_msg = f"Error processing post_id={post_id}: {str(e)}"
                results["errors"].append(error_msg)
                results["failed"] += 1

    finally:
        # Save all logs to GCS at the end of execution
        log_file_uri = save_execution_logs(
            requested_max_posts=max_posts,
            available_posts=available_posts_count,
        )
        if log_file_uri:
            results["log_file"] = log_file_uri

    return results
