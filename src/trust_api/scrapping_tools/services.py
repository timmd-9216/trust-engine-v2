"""Services for scrapping-tools."""

import io
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from google.cloud import firestore, storage

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:
    pa = None
    pq = None

from trust_api.scrapping_tools.core.config import settings

logger = logging.getLogger(__name__)


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
    Results are prioritized by platform (twitter first), then ordered by created_at (oldest first).

    Args:
        max_posts: Maximum number of posts to return. If None, returns all posts.

    Returns:
        List of post documents with fields: post_id, country, platform, candidate_id, etc.
        Each document also includes '_doc_id' field with the Firestore document ID.
        Posts are returned with twitter posts first, then other platforms, all ordered by created_at.
    """
    client = get_firestore_client()
    posts = []

    # First, get twitter posts (prioritized)
    # Requires index: status + platform + created_at
    twitter_query = (
        client.collection(settings.firestore_collection)
        .where("status", "==", "noreplies")
        .where("platform", "==", "twitter")
        .order_by("created_at")  # Order by created_at ascending (oldest first)
    )

    twitter_posts = []
    for doc in twitter_query.stream():
        doc_data = doc.to_dict()
        doc_data["_doc_id"] = doc.id
        twitter_posts.append(doc_data)

    posts.extend(twitter_posts)

    # If we haven't reached max_posts, get posts from other platforms
    if max_posts is None or len(posts) < max_posts:
        # Get all posts with status='noreplies' ordered by created_at
        # We'll filter out twitter posts in Python since Firestore doesn't support != operator
        other_query = (
            client.collection(settings.firestore_collection)
            .where("status", "==", "noreplies")
            .order_by("created_at")  # Order by created_at ascending (oldest first)
        )

        other_posts = []
        for doc in other_query.stream():
            # Stop if we've reached the limit
            if max_posts is not None and len(posts) + len(other_posts) >= max_posts:
                break

            doc_data = doc.to_dict()
            platform = doc_data.get("platform", "").lower()
            # Skip twitter posts (already included in first query)
            if platform != "twitter":
                doc_data["_doc_id"] = doc.id
                other_posts.append(doc_data)

        posts.extend(other_posts)

    # Apply final limit if specified (shouldn't be necessary, but just in case)
    if max_posts is not None and max_posts > 0:
        posts = posts[:max_posts]

    return posts


# Global list to accumulate logs during execution
_execution_logs: list[dict[str, Any]] = []

# Global list to accumulate error logs (for empty results and other errors)
_error_logs: list[dict[str, Any]] = []


def reset_execution_logs() -> None:
    """Reset the execution logs list for a new execution."""
    global _execution_logs, _error_logs
    _execution_logs = []
    _error_logs = []


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
    is_retry: bool = False,
    retry_count: int = 0,
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
        is_retry: Whether this is a retry attempt (default: False)
        retry_count: Number of retry attempt (default: 0)
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
        "is_retry": is_retry,
        "retry_count": retry_count,
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

        # Get API usage information
        api_usage = None
        try:
            from trust_api.scrapping_tools.information_tracer import check_api_usage

            if settings.information_tracer_api_key:
                api_usage = check_api_usage(settings.information_tracer_api_key)
        except Exception as e:
            # Log the error but don't fail the entire logging process
            api_usage = {"error": f"Failed to check API usage: {str(e)}"}

        # Create log file content with metadata and all entries
        log_file = {
            "execution_timestamp": now.isoformat(),
            "requested_max_posts": requested_max_posts,
            "available_posts": available_posts,
            "total_entries": total_calls,
            "api_calls": api_calls,
            "skipped_posts": skipped_count,
            "api_usage": api_usage,  # Include API usage information
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


def add_error_entry(
    job_id: str,
    post_id: str,
    platform: str,
    country: str,
    candidate_id: str,
    error_type: str,
    error_message: str,
    job_doc_id: str | None = None,
) -> None:
    """
    Add an error entry to the error logs list.

    Args:
        job_id: The Information Tracer job ID
        post_id: The post ID
        platform: The platform name
        country: The country name
        candidate_id: The candidate ID
        error_type: Type of error (e.g., "empty_result", "retry_still_empty")
        error_message: Detailed error message
        job_doc_id: The Firestore job document ID (optional)
    """
    global _error_logs
    now = datetime.now(timezone.utc)

    error_entry = {
        "timestamp": now.isoformat(),
        "job_id": job_id,
        "post_id": post_id,
        "platform": platform,
        "country": country,
        "candidate_id": candidate_id,
        "error_type": error_type,
        "error_message": error_message,
        "job_doc_id": job_doc_id,
        "gcs_path": _get_gcs_blob_path(country, platform, candidate_id, post_id),
    }

    _error_logs.append(error_entry)


def save_error_logs(
    execution_type: str = "process-jobs",
    requested_max_items: int | None = None,
    available_items: int | None = None,
) -> str | None:
    """
    Save all accumulated error logs to GCS bucket in logs/errors/ folder.
    Uses a single file per execution.

    Args:
        execution_type: Type of execution (e.g., "process-jobs", "fix-jobs")
        requested_max_items: Maximum number of items requested in the API call (if specified)
        available_items: Total number of items available (if specified)

    Returns:
        GCS URI of the saved error log file, or None if logging fails or is disabled
    """
    if not settings.gcs_bucket_name:
        return None

    if not _error_logs:
        # No errors to save
        return None

    try:
        client = get_gcs_client()
        bucket = client.bucket(settings.gcs_bucket_name)

        # Create filename: errors/YYYY-MM-DD/HH-MM-SS-{timestamp}.json
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H-%M-%S-%f")[:-3]  # Include milliseconds
        filename = f"{time_str}.json"
        blob_path = f"logs/errors/{date_str}/{filename}"

        # Calculate summary statistics
        total_errors = len(_error_logs)
        error_types = {}
        for error in _error_logs:
            error_type = error.get("error_type", "unknown")
            error_types[error_type] = error_types.get(error_type, 0) + 1

        # Get API usage information (especially important when there are errors)
        api_usage = None
        try:
            from trust_api.scrapping_tools.information_tracer import check_api_usage

            if settings.information_tracer_api_key:
                api_usage = check_api_usage(settings.information_tracer_api_key)
        except Exception as e:
            # Log the error but don't fail the entire logging process
            api_usage = {"error": f"Failed to check API usage: {str(e)}"}

        # Create error log file content with metadata and all entries
        error_file = {
            "execution_timestamp": now.isoformat(),
            "execution_type": execution_type,
            "requested_max_items": requested_max_items,
            "available_items": available_items,
            "total_errors": total_errors,
            "error_types": error_types,
            "api_usage": api_usage,  # Include API usage information (important for debugging errors)
            "errors": _error_logs,
        }

        blob = bucket.blob(blob_path)
        blob.upload_from_string(
            json.dumps(error_file, ensure_ascii=False, indent=2),
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
    sort_by: Literal["time", "engagement"] = "time",
) -> dict[str, Any]:
    """
    Fetch replies for a post using Information Tracer API.
    Logs all calls to GCS bucket in logs/ folder.

    Args:
        post_id: The post ID to get replies for
        platform: The platform where the post is located (twitter, facebook, instagram, etc.)
        max_posts: Maximum number of replies to collect (default: 100)
        sort_by: Sort order for replies ('time' or 'engagement'). Default is 'time'.
                 Note: Only applies to keyword search, not account search.

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
            sort_by=sort_by,
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


def rename_existing_gcs_file(
    country: str,
    platform: str,
    candidate_id: str,
    post_id: str,
) -> str | None:
    """
    Rename an existing GCS file by adding 'old-[timestamp]-' prefix to the filename.

    Args:
        country: Country name
        platform: Platform name
        candidate_id: Candidate ID
        post_id: Post ID (used for filename)

    Returns:
        New blob path if file was renamed, None if file didn't exist or rename failed.

    Raises:
        ValueError: If GCS_BUCKET_NAME is not configured
    """
    if not settings.gcs_bucket_name:
        raise ValueError("GCS_BUCKET_NAME is not configured")

    try:
        client = get_gcs_client()
        bucket = client.bucket(settings.gcs_bucket_name)

        # Get original blob path
        original_blob_path = _get_gcs_blob_path(country, platform, candidate_id, post_id)
        original_blob = bucket.blob(original_blob_path)

        # Check if blob exists
        if not original_blob.exists():
            return None

        # Generate new blob path with 'old-[timestamp]-' prefix
        # Format: raw/{country}/{platform}/{candidate_id}/old-{timestamp}-{post_id}.json
        now = datetime.now(timezone.utc)
        timestamp_str = now.strftime("%Y%m%d-%H%M%S")

        # Normalize path components
        safe_country = country.replace("/", "_").replace("\\", "_")
        safe_platform = platform.replace("/", "_").replace("\\", "_")
        safe_candidate_id = str(candidate_id).replace("/", "_").replace("\\", "_")
        safe_post_id = str(post_id).replace("/", "_").replace("\\", "_")

        new_filename = f"old-{timestamp_str}-{safe_post_id}.json"
        new_blob_path = f"raw/{safe_country}/{safe_platform}/{safe_candidate_id}/{new_filename}"

        # Copy blob to new location
        bucket.copy_blob(original_blob, bucket, new_blob_path)

        # Delete original blob
        original_blob.delete()

        logger.info(f"Renamed existing GCS file: {original_blob_path} -> {new_blob_path}")

        return new_blob_path
    except Exception as e:
        logger.error(f"Error renaming GCS file for post_id={post_id}: {str(e)}")
        # Return None on error - we'll continue processing anyway
        return None


def _is_result_empty(result: dict[str, Any] | list[Any]) -> bool:
    """
    Check if a result is empty or contains no useful data.

    Args:
        result: The result data to check (dict or list)

    Returns:
        True if the result is empty or contains no useful data, False otherwise
    """
    if result is None:
        return True

    # Check if it's an empty list
    if isinstance(result, list):
        return len(result) == 0

    # Check if it's an empty dict
    if isinstance(result, dict):
        if len(result) == 0:
            return True

        # Check if all values are empty (None, empty strings, empty lists, empty dicts)
        for value in result.values():
            if value is None:
                continue
            if isinstance(value, str) and value.strip() == "":
                continue
            if isinstance(value, (list, dict)) and len(value) == 0:
                continue
            # If we find at least one non-empty value, the result is not empty
            return False

        # All values were empty
        return True

    return False


def save_to_gcs(
    data: dict[str, Any],
    country: str,
    platform: str,
    candidate_id: str,
    post_id: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    """
    Save JSON data to GCS bucket with structure: country/platform/candidate_id/{post_id}.json

    Args:
        data: JSON data to save
        country: Country name
        platform: Platform name
        candidate_id: Candidate ID
        post_id: Post ID (used for filename)
        metadata: Optional metadata to include in the saved JSON (e.g., retry information)

    Returns:
        GCS URI of the saved file

    Raises:
        ValueError: If GCS_BUCKET_NAME is not configured or if data is empty
    """
    if not settings.gcs_bucket_name:
        raise ValueError("GCS_BUCKET_NAME is not configured")

    # Validate that data is not empty
    if _is_result_empty(data):
        raise ValueError("Cannot save empty result to GCS")

    client = get_gcs_client()
    bucket = client.bucket(settings.gcs_bucket_name)

    blob_path = _get_gcs_blob_path(country, platform, candidate_id, post_id)

    # Prepare data to save (add metadata if provided)
    data_to_save = data.copy()
    if metadata:
        # Add metadata at the top level of the JSON
        data_to_save["_metadata"] = metadata

    blob = bucket.blob(blob_path)
    blob.upload_from_string(
        json.dumps(data_to_save, ensure_ascii=False, indent=2),
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


def has_existing_job_for_post(post_id: str) -> bool:
    """
    Check if there's already a pending or processing job for a given post.

    Args:
        post_id: The post ID to check

    Returns:
        True if there's an existing pending or processing job, False otherwise
    """
    client = get_firestore_client()

    # Check for pending jobs
    pending_query = (
        client.collection(settings.firestore_jobs_collection)
        .where("post_id", "==", post_id)
        .where("status", "==", "pending")
        .limit(1)
    )
    if list(pending_query.stream()):
        return True

    # Check for processing jobs
    processing_query = (
        client.collection(settings.firestore_jobs_collection)
        .where("post_id", "==", post_id)
        .where("status", "==", "processing")
        .limit(1)
    )
    if list(processing_query.stream()):
        return True

    return False


def save_pending_job(
    job_id: str,
    post_doc_id: str,
    post_id: str,
    platform: str,
    country: str,
    candidate_id: str,
    max_posts: int,
    sort_by: Literal["time", "engagement"] = "time",
) -> str:
    """
    Save a pending job to Firestore jobs collection.

    Args:
        job_id: The Information Tracer job ID (hash_id)
        post_doc_id: The Firestore document ID of the post
        post_id: The post ID
        platform: The platform name
        country: The country name
        candidate_id: The candidate ID
        max_posts: Maximum number of posts to fetch
        sort_by: Sort order for replies ('time' or 'engagement'). Default is 'time'.

    Returns:
        The Firestore document ID of the created job

    Raises:
        ValueError: If required parameters are missing
    """
    if not job_id or not post_doc_id or not post_id:
        raise ValueError("job_id, post_doc_id, and post_id are required")

    client = get_firestore_client()
    now = datetime.now(timezone.utc)

    job_data = {
        "job_id": job_id,
        "post_doc_id": post_doc_id,
        "post_id": post_id,
        "platform": platform,
        "country": country,
        "candidate_id": candidate_id,
        "max_posts": max_posts,
        "sort_by": sort_by,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
    }

    doc_ref = client.collection(settings.firestore_jobs_collection).document()
    doc_ref.set(job_data)

    # Update post status to "processing" to prevent duplicate job creation
    if post_doc_id:
        try:
            update_post_status(post_doc_id, "processing")
        except Exception as e:
            # Log but don't fail if post update fails
            logger.warning(f"Could not update post {post_doc_id} to 'processing': {str(e)}")

    return doc_ref.id


def query_pending_jobs(max_jobs: int | None = None) -> list[dict[str, Any]]:
    """
    Query Firestore for pending jobs.
    Results are ordered by created_at (oldest first).

    Args:
        max_jobs: Maximum number of jobs to return. If None, returns all jobs.

    Returns:
        List of job documents with fields: job_id, post_doc_id, post_id, etc.
        Each document also includes '_doc_id' field with the Firestore document ID.
    """
    client = get_firestore_client()
    query = (
        client.collection(settings.firestore_jobs_collection)
        .where("status", "==", "pending")
        .order_by("created_at")  # Order by created_at ascending (oldest first)
    )

    # Apply limit if specified
    if max_jobs is not None and max_jobs > 0:
        query = query.limit(max_jobs)

    jobs = []
    for doc in query.stream():
        doc_data = doc.to_dict()
        doc_data["_doc_id"] = doc.id  # Store document ID for later update
        jobs.append(doc_data)

    return jobs


def query_done_jobs(max_jobs: int | None = None) -> list[dict[str, Any]]:
    """
    Query Firestore for done jobs.
    Results are ordered by updated_at (oldest first).

    Args:
        max_jobs: Maximum number of jobs to return. If None, returns all jobs.

    Returns:
        List of job documents with fields: job_id, post_doc_id, post_id, etc.
        Each document also includes '_doc_id' field with the Firestore document ID.
    """
    client = get_firestore_client()
    query = (
        client.collection(settings.firestore_jobs_collection)
        .where("status", "==", "done")
        .order_by("updated_at")  # Order by updated_at ascending (oldest first)
    )

    # Apply limit if specified
    if max_jobs is not None and max_jobs > 0:
        query = query.limit(max_jobs)

    jobs = []
    for doc in query.stream():
        doc_data = doc.to_dict()
        doc_data["_doc_id"] = doc.id  # Store document ID for later update
        jobs.append(doc_data)

    return jobs


def count_jobs_by_status(
    status: str,
    candidate_id: str | None = None,
    platform: str | None = None,
    country: str | None = None,
    updated_today: bool = False,
) -> int:
    """
    Count jobs with a specific status in Firestore.

    Args:
        status: Job status to count ('pending', 'empty_result', 'done', 'failed', etc.)
        candidate_id: Optional candidate_id to filter jobs
        platform: Optional platform to filter jobs (e.g., 'twitter', 'instagram')
        country: Optional country to filter jobs
        updated_today: If True, only count jobs updated today (based on updated_at field)

    Returns:
        Total count of jobs with the specified status matching the filters
    """
    client = get_firestore_client()
    query = client.collection(settings.firestore_jobs_collection).where("status", "==", status)

    # Apply optional filters
    if candidate_id:
        query = query.where("candidate_id", "==", candidate_id)
    if platform:
        query = query.where("platform", "==", platform.lower())
    if country:
        query = query.where("country", "==", country.lower())

    # Count documents (Firestore doesn't have a direct count, so we iterate)
    # Note: For updated_today queries, we'll filter in Python to avoid index requirements
    count = 0
    if updated_today:
        now = datetime.now(timezone.utc)
        start_of_day = datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=timezone.utc)
        end_of_day = datetime(now.year, now.month, now.day, 23, 59, 59, 999999, tzinfo=timezone.utc)
        # Filter in Python to avoid composite index requirement
        for doc in query.stream():
            doc_data = doc.to_dict()
            updated_at = doc_data.get("updated_at")
            if updated_at:
                if hasattr(updated_at, "timestamp"):
                    updated_dt = updated_at
                elif isinstance(updated_at, datetime):
                    updated_dt = updated_at
                else:
                    continue

                if start_of_day <= updated_dt <= end_of_day:
                    count += 1
    else:
        for _ in query.stream():
            count += 1

    return count


def count_empty_result_jobs(
    candidate_id: str | None = None,
    platform: str | None = None,
    country: str | None = None,
) -> int:
    """
    Count jobs with status='empty_result' in Firestore.

    This is a convenience wrapper around count_jobs_by_status for backward compatibility.

    Args:
        candidate_id: Optional candidate_id to filter jobs
        platform: Optional platform to filter jobs (e.g., 'twitter', 'instagram')
        country: Optional country to filter jobs

    Returns:
        Total count of jobs with status='empty_result' matching the filters
    """
    return count_jobs_by_status(
        status="empty_result",
        candidate_id=candidate_id,
        platform=platform,
        country=country,
    )


def count_posts_by_status(
    status: str,
    candidate_id: str | None = None,
    platform: str | None = None,
    country: str | None = None,
    updated_today: bool = False,
) -> int:
    """
    Count posts with a specific status in Firestore.

    Args:
        status: Post status to count ('noreplies', 'done', 'skipped')
        candidate_id: Optional candidate_id to filter posts
        platform: Optional platform to filter posts (e.g., 'twitter', 'instagram')
        country: Optional country to filter posts
        updated_today: If True, only count posts updated today (based on updated_at field)

    Returns:
        Total count of posts with the specified status matching the filters
    """
    client = get_firestore_client()
    query = client.collection(settings.firestore_collection).where("status", "==", status)

    # Apply optional filters
    if candidate_id:
        query = query.where("candidate_id", "==", candidate_id)
    if platform:
        query = query.where("platform", "==", platform.lower())
    if country:
        query = query.where("country", "==", country.lower())

    # Count documents (Firestore doesn't have a direct count, so we iterate)
    # Note: For updated_today queries, we'll filter in Python to avoid index requirements
    count = 0
    if updated_today:
        now = datetime.now(timezone.utc)
        start_of_day = datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=timezone.utc)
        end_of_day = datetime(now.year, now.month, now.day, 23, 59, 59, 999999, tzinfo=timezone.utc)
        # Filter in Python to avoid composite index requirement
        for doc in query.stream():
            doc_data = doc.to_dict()
            updated_at = doc_data.get("updated_at")
            if updated_at:
                if hasattr(updated_at, "timestamp"):
                    updated_dt = updated_at
                elif isinstance(updated_at, datetime):
                    updated_dt = updated_at
                else:
                    continue

                if start_of_day <= updated_dt <= end_of_day:
                    count += 1
    else:
        for _ in query.stream():
            count += 1

    return count


def update_job_status(doc_id: str, new_status: str) -> None:
    """
    Update the status field of a job document and set updated_at timestamp.

    Args:
        doc_id: The Firestore document ID of the job to update
        new_status: The new status value ('pending', 'processing', 'done', 'failed', 'quota_exceeded', 'empty_result', 'verified')

    Raises:
        ValueError: If doc_id is not provided
    """
    if not doc_id:
        raise ValueError("doc_id is required to update job status")

    client = get_firestore_client()
    doc_ref = client.collection(settings.firestore_jobs_collection).document(doc_id)

    # Get current timestamp in UTC
    now = datetime.now(timezone.utc)

    # Update both status and updated_at
    doc_ref.update(
        {
            "status": new_status,
            "updated_at": now,
        }
    )


def increment_job_retry_count(doc_id: str) -> int:
    """
    Increment the retry_count field of a job document.
    If retry_count doesn't exist, it's initialized to 1.

    Args:
        doc_id: The Firestore document ID of the job to update

    Returns:
        The new retry_count value

    Raises:
        ValueError: If doc_id is not provided
    """
    if not doc_id:
        raise ValueError("doc_id is required to increment retry count")

    client = get_firestore_client()
    doc_ref = client.collection(settings.firestore_jobs_collection).document(doc_id)

    # Get current document to check existing retry_count
    doc = doc_ref.get()
    if doc.exists:
        current_data = doc.to_dict()
        current_retry_count = current_data.get("retry_count", 0)
        new_retry_count = current_retry_count + 1
    else:
        new_retry_count = 1

    # Update retry_count and updated_at
    now = datetime.now(timezone.utc)
    doc_ref.update({"retry_count": new_retry_count, "updated_at": now})

    return new_retry_count


def update_job_with_log_files(
    doc_id: str,
    execution_log_file: str | None = None,
    error_log_file: str | None = None,
) -> None:
    """
    Update job document with references to log files (optional feature).

    This function only updates jobs if ENABLE_JOB_LOG_REFERENCES is enabled.
    By default, this feature is disabled to minimize Firestore write operations.

    Args:
        doc_id: The Firestore document ID of the job to update
        execution_log_file: GCS URI of the execution log file (optional)
        error_log_file: GCS URI of the error log file (optional)

    Note:
        This is an optional feature controlled by ENABLE_JOB_LOG_REFERENCES env var.
        When disabled (default), this function does nothing to avoid unnecessary Firestore writes.
    """
    # Check if feature is enabled
    if not settings.enable_job_log_references:
        return

    if not doc_id:
        return

    try:
        client = get_firestore_client()
        doc_ref = client.collection(settings.firestore_jobs_collection).document(doc_id)

        update_data: dict[str, str] = {}
        if execution_log_file:
            update_data["execution_log_file"] = execution_log_file
        if error_log_file:
            update_data["error_log_file"] = error_log_file

        if update_data:
            doc_ref.update(update_data)
    except Exception as e:
        # Silently fail to avoid breaking the main flow
        # Log warning but don't raise exception
        logger.warning(f"Could not update job {doc_id} with log file references: {str(e)}")


def update_jobs_with_log_files(
    job_doc_ids: list[str],
    execution_log_file: str | None = None,
    error_log_file: str | None = None,
) -> None:
    """
    Update multiple job documents with references to log files (optional feature).

    This is a batch version of update_job_with_log_files() for efficiency.

    Args:
        job_doc_ids: List of Firestore document IDs of jobs to update
        execution_log_file: GCS URI of the execution log file (optional)
        error_log_file: GCS URI of the error log file (optional)

    Note:
        This is an optional feature controlled by ENABLE_JOB_LOG_REFERENCES env var.
        When disabled (default), this function does nothing to avoid unnecessary Firestore writes.
    """
    # Check if feature is enabled
    if not settings.enable_job_log_references:
        return

    if not job_doc_ids:
        return

    # Update each job (Firestore doesn't support batch updates for different documents easily)
    for doc_id in job_doc_ids:
        update_job_with_log_files(
            doc_id=doc_id,
            execution_log_file=execution_log_file,
            error_log_file=error_log_file,
        )


def retry_job_from_empty_result(doc_id: str) -> int:
    """
    Move a job from 'empty_result' status to 'pending' and increment retry_count.
    This is used when manually reprocessing jobs that had empty results.

    IMPORTANT: This function reuses the SAME job document. It does NOT create a new job.
    The job_id (Information Tracer hash) remains the same, and the post_doc_id reference
    is preserved. Only the status, retry_count, and updated_at fields are updated.

    The associated post is also updated to 'noreplies' status to allow reprocessing,
    but only if it's currently in 'done' status (to avoid interfering with other operations).

    Args:
        doc_id: The Firestore document ID of the job to retry

    Returns:
        The new retry_count value

    Raises:
        ValueError: If doc_id is not provided
    """
    if not doc_id:
        raise ValueError("doc_id is required to retry job from empty_result")

    client = get_firestore_client()
    doc_ref = client.collection(settings.firestore_jobs_collection).document(doc_id)

    # Get current document to check status and retry_count
    doc = doc_ref.get()
    if not doc.exists:
        raise ValueError(f"Job document {doc_id} does not exist")

    current_data = doc.to_dict()
    current_status = current_data.get("status")
    post_doc_id = current_data.get("post_doc_id")

    # Verify that the job is in empty_result status
    if current_status != "empty_result":
        logger.warning(
            f"Job {doc_id} is not in 'empty_result' status (current: {current_status}). "
            f"Proceeding anyway, but this may not be a retry from empty_result."
        )

    # Increment retry_count
    current_retry_count = current_data.get("retry_count", 0)
    new_retry_count = current_retry_count + 1

    # Update status to pending, increment retry_count, and update timestamp
    now = datetime.now(timezone.utc)
    doc_ref.update(
        {
            "status": "pending",
            "retry_count": new_retry_count,
            "updated_at": now,
        }
    )

    # Update associated post to 'noreplies' if it's in 'done' status
    # This allows the post to be reprocessed, but only if it was already done
    # (to avoid interfering with posts that might be in other states)
    if post_doc_id:
        try:
            post_ref = client.collection(settings.firestore_collection).document(post_doc_id)
            post_doc = post_ref.get()
            if post_doc.exists:
                post_data = post_doc.to_dict()
                post_status = post_data.get("status")
                # Only update if post is in 'done' status (was successfully processed before)
                if post_status == "done":
                    post_ref.update({"status": "noreplies", "updated_at": now})
                    logger.info(f"Updated post {post_doc_id} from 'done' to 'noreplies' for retry")
        except Exception as e:
            # Log but don't fail if post update fails
            logger.warning(f"Could not update post {post_doc_id} status during retry: {str(e)}")

    logger.info(
        f"Retrying job {doc_id} from empty_result (retry #{new_retry_count}). "
        f"Status updated to 'pending'. Job document reused (same job_id, same post_doc_id)."
    )

    return new_retry_count


def query_empty_result_jobs(
    candidate_id: str | None = None,
    platform: str | None = None,
    country: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """
    Query Firestore for jobs with status='empty_result'.

    Args:
        candidate_id: Optional candidate_id to filter jobs
        platform: Optional platform to filter jobs (e.g., 'twitter', 'instagram')
        country: Optional country to filter jobs
        limit: Maximum number of jobs to return. If None, returns all matching jobs.

    Returns:
        List of job documents with fields: job_id, post_doc_id, post_id, etc.
        Each document also includes '_doc_id' field with the Firestore document ID.
    """
    client = get_firestore_client()
    query = (
        client.collection(settings.firestore_jobs_collection)
        .where("status", "==", "empty_result")
        .order_by("updated_at")
    )

    # Apply optional filters
    if candidate_id:
        query = query.where("candidate_id", "==", candidate_id)
    if platform:
        query = query.where("platform", "==", platform.lower())
    if country:
        query = query.where("country", "==", country.lower())

    # Apply limit if specified
    if limit is not None and limit > 0:
        query = query.limit(limit)

    jobs = []
    for doc in query.stream():
        doc_data = doc.to_dict()
        doc_data["_doc_id"] = doc.id  # Store document ID
        jobs.append(doc_data)

    return jobs


def retry_empty_result_jobs_service(
    candidate_id: str | None = None,
    platform: str | None = None,
    country: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """
    Retry jobs with status='empty_result' by moving them to 'pending' status.

    This service:
    1. Queries Firestore for jobs with status='empty_result' (with optional filters)
    2. Moves each job to 'pending' status using retry_job_from_empty_result()
    3. Increments retry_count automatically
    4. Ensures logs will show these as retries when processed

    Args:
        candidate_id: Optional candidate_id to filter jobs
        platform: Optional platform to filter jobs (e.g., 'twitter', 'instagram')
        country: Optional country to filter jobs
        limit: Maximum number of jobs to retry. If None, retries all matching jobs.

    Returns:
        Dictionary with processing results including:
        - total_found: Total number of empty_result jobs found
        - retried: Number of jobs successfully retried
        - errors: List of error messages
        - retried_jobs: List of jobs that were retried with their details
    """
    results = {
        "total_found": 0,
        "retried": 0,
        "errors": [],
        "retried_jobs": [],
    }

    try:
        # Query empty_result jobs
        jobs = query_empty_result_jobs(
            candidate_id=candidate_id,
            platform=platform,
            country=country,
            limit=limit,
        )
        results["total_found"] = len(jobs)

        # Retry each job
        for job in jobs:
            doc_id = job.get("_doc_id")
            job_id = job.get("job_id")
            post_id = job.get("post_id")
            platform_job = job.get("platform", "unknown")
            country_job = job.get("country", "unknown")
            candidate_id_job = job.get("candidate_id", "unknown")
            current_retry_count = job.get("retry_count", 0)

            if not doc_id:
                error_msg = f"Job missing _doc_id: job_id={job_id}, post_id={post_id}"
                results["errors"].append(error_msg)
                continue

            try:
                # Retry the job
                new_retry_count = retry_job_from_empty_result(doc_id)
                results["retried"] += 1
                results["retried_jobs"].append(
                    {
                        "doc_id": doc_id,
                        "job_id": job_id,
                        "post_id": post_id,
                        "platform": platform_job,
                        "country": country_job,
                        "candidate_id": candidate_id_job,
                        "previous_retry_count": current_retry_count,
                        "new_retry_count": new_retry_count,
                    }
                )
            except Exception as e:
                error_msg = (
                    f"Error retrying job {doc_id} (job_id={job_id}, post_id={post_id}): {str(e)}"
                )
                results["errors"].append(error_msg)
                logger.error(error_msg)

    except Exception as e:
        error_msg = f"Error querying empty_result jobs: {str(e)}"
        results["errors"].append(error_msg)
        logger.error(error_msg)

    return results


def submit_post_job(
    post_id: str,
    platform: str,
    max_posts: int = 100,
    sort_by: Literal["time", "engagement"] = "time",
) -> str | None:
    """
    Submit a post replies job to Information Tracer API and return the job ID (hash_id).
    This function only submits the job, it does not wait for completion.

    Args:
        post_id: The post ID to get replies for
        platform: The platform where the post is located (twitter, facebook, instagram, etc.)
        max_posts: Maximum number of replies to collect (default: 100)
        sort_by: Sort order for replies ('time' or 'engagement'). Default is 'time'.
                 Note: Only applies to keyword search, not account search.

    Returns:
        The job ID (id_hash256) if submission is successful, None otherwise

    Raises:
        ValueError: If INFORMATION_TRACER_API_KEY is not configured or invalid platform
    """
    if not settings.information_tracer_api_key:
        raise ValueError("INFORMATION_TRACER_API_KEY is not configured")

    # Import here to avoid circular dependencies
    from trust_api.scrapping_tools.information_tracer import PlatformType, submit

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

    # Construct query for reply search: 'reply:post_id'
    query = f"reply:{post_id}"

    # Default parameters for reply collection
    timeline_only = False
    enable_ai = False
    start_date = "2020-01-01"
    end_date = "2025-12-31"

    # Submit the job
    id_hash256, _ = submit(
        token=settings.information_tracer_api_key,
        query=query,
        max_post=max_posts,
        sort_by=sort_by,
        start_date=start_date,
        end_date=end_date,
        platform=platform.lower(),  # type: ignore
        timeline_only=timeline_only,
        enable_ai=enable_ai,
    )

    return id_hash256


def process_posts_service(
    max_posts: int | None = None,
    sort_by: Literal["time", "engagement"] = "time",
) -> dict[str, Any]:
    """
    Submit jobs to Information Tracer API and save hash_ids to pending_jobs collection.
    This function only submits the jobs, it does not wait for completion.

    Args:
        max_posts: Maximum number of posts to process. If None, processes all posts with status='noreplies'.
        sort_by: Sort order for replies ('time' or 'engagement'). Default is 'time'.
                 Note: Only applies to keyword search, not account search.

    Returns:
        Dictionary with processing results including success count, errors, jobs created, etc.
    """
    # Reset logs for this execution
    reset_execution_logs()

    results = {
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "skipped": 0,
        "errors": [],
        "jobs_created": [],
    }

    # Track job document IDs created during this execution (for optional log file references)
    created_job_doc_ids: list[str] = []

    try:
        # Query all posts without replies
        all_posts = query_posts_without_replies(max_posts=None)

        # Apply limit if specified (limit in Python to avoid second query)
        if max_posts is not None and max_posts > 0:
            posts = all_posts[:max_posts]
        else:
            posts = all_posts

        results["processed"] = len(posts)

        for index, post in enumerate(posts):
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
                # Determine maximum posts to fetch from Information Tracer
                # Priority: max_replies > replies_count > default (100)
                replies_count = post.get("replies_count")
                max_replies = post.get("max_replies")

                # Use max_replies if available and valid (has priority)
                if max_replies is not None and max_replies > 0:
                    max_posts_to_fetch = max_replies
                # Fallback to replies_count if max_replies is not available
                elif replies_count is not None and replies_count > 0:
                    max_posts_to_fetch = replies_count
                else:
                    # Default to 100 if neither is available or both are invalid
                    max_posts_to_fetch = 100

                # Skip posts with no replies expected
                if (replies_count is None or replies_count <= 0) and (
                    max_replies is None or max_replies <= 0
                ):
                    results["skipped"] += 1
                    # Update status to "skipped" in Firestore
                    if doc_id:
                        update_post_status(doc_id, "skipped")
                    # Log the skipped post
                    add_log_entry(
                        post_id=post_id,
                        url="N/A",
                        success=False,
                        skipped=True,
                        skip_reason=f"max_replies={max_replies}, replies_count={replies_count} (no replies expected)",
                        max_replies=max_replies or replies_count or 0,
                    )
                    continue

                # Check if JSON already exists in GCS
                info_data = read_from_gcs_if_exists(
                    country=country,
                    platform=platform,
                    candidate_id=candidate_id,
                    post_id=post_id,
                )

                if info_data is not None:
                    # File already exists - rename it with 'old-[timestamp]-' prefix
                    old_file_path = rename_existing_gcs_file(
                        country=country,
                        platform=platform,
                        candidate_id=candidate_id,
                        post_id=post_id,
                    )
                    if old_file_path:
                        logger.info(
                            f"Renamed existing file for post_id={post_id} to {old_file_path}. "
                            f"Will create new job to reprocess."
                        )
                        add_log_entry(
                            post_id=post_id,
                            url="N/A",
                            success=True,
                            skipped=False,
                            skip_reason=f"Renamed existing file to {old_file_path}",
                            max_replies=max_posts_to_fetch,
                        )
                    else:
                        # If rename failed, log warning but continue anyway
                        logger.warning(
                            f"Failed to rename existing file for post_id={post_id}. "
                            f"Will attempt to create new job anyway."
                        )

                # Check if there's already a pending or processing job for this post
                if has_existing_job_for_post(post_id):
                    results["skipped"] += 1
                    add_log_entry(
                        post_id=post_id,
                        url="N/A",
                        success=False,
                        skipped=True,
                        skip_reason="Job already exists (pending or processing)",
                    )
                    continue

                # Submit job to Information Tracer
                job_id = submit_post_job(
                    post_id=post_id,
                    platform=platform,
                    max_posts=max_posts_to_fetch,
                    sort_by=sort_by,
                )

                if job_id:
                    # Save job to pending_jobs collection
                    job_doc_id = save_pending_job(
                        job_id=job_id,
                        post_doc_id=doc_id,
                        post_id=post_id,
                        platform=platform,
                        country=country,
                        candidate_id=candidate_id,
                        max_posts=max_posts_to_fetch,
                        sort_by=sort_by,
                    )
                    results["jobs_created"].append(
                        {
                            "job_id": job_id,
                            "job_doc_id": job_doc_id,
                            "post_id": post_id,
                        }
                    )
                    # Track this job for optional log file references
                    if job_doc_id:
                        created_job_doc_ids.append(job_doc_id)
                    results["succeeded"] += 1
                    # Log successful job submission
                    add_log_entry(
                        post_id=post_id,
                        url=f"https://informationtracer.com/submit (reply:{post_id})",
                        success=True,
                        status_code=200,
                        job_id=job_id,
                        max_replies=max_posts_to_fetch,
                    )
                else:
                    error_msg = f"Failed to submit job for post_id={post_id}"
                    results["errors"].append(error_msg)
                    results["failed"] += 1
                    # Log the failed submission in execution logs
                    add_log_entry(
                        post_id=post_id,
                        url=f"https://informationtracer.com/submit (reply:{post_id})",
                        success=False,
                        error_message="Failed to submit job to Information Tracer",
                        max_replies=max_posts_to_fetch,
                    )
                    # Also add to error logs
                    add_error_entry(
                        job_id=None,  # No job_id since submit failed
                        post_id=post_id,
                        platform=platform,
                        country=country,
                        candidate_id=candidate_id,
                        error_type="submit_failed",
                        error_message="Failed to submit job to Information Tracer API",
                        job_doc_id=None,
                    )
                    # Stop processing when submit fails - likely API quota/rate limit issue
                    break

            except Exception as e:
                error_msg = f"Error processing post_id={post_id}: {str(e)}"
                results["errors"].append(error_msg)
                results["failed"] += 1

    finally:
        # Always save logs if there are any (especially important when execution stops early due to submit failure)
        if _execution_logs:
            log_file_uri = save_execution_logs(
                requested_max_posts=max_posts,
                available_posts=results["processed"],
            )
            if log_file_uri:
                results["log_file"] = log_file_uri

        # Save error logs if there are any errors (especially "Failed to submit job" errors)
        if _error_logs:
            error_file_uri = save_error_logs(
                execution_type="process-posts",
                requested_max_items=max_posts,
                available_items=results["processed"],
            )
            if error_file_uri:
                results["error_log_file"] = error_file_uri

        # Update created jobs with log file references (optional feature)
        if created_job_doc_ids:
            update_jobs_with_log_files(
                job_doc_ids=created_job_doc_ids,
                execution_log_file=log_file_uri,
                error_log_file=error_file_uri if _error_logs else None,
            )

    return results


def process_pending_jobs_service(max_jobs: int | None = None) -> dict[str, Any]:
    """
    Process pending jobs from Firestore jobs collection.

    **Quota Check:** Before processing any jobs, checks Information Tracer API quota.
    If quota is exceeded (400/400), returns early without processing to avoid wasted API calls.

    For each job (if quota allows):
    1. Check job status with Information Tracer API
    2. If finished, retrieve results
    3. Save results to GCS
    4. Update post status to 'done' in Firestore
    5. Update job status to 'done' in Firestore

    Args:
        max_jobs: Maximum number of jobs to process. If None, processes all pending jobs.

    Returns:
        Dictionary with processing results including success count, errors, etc.
        If quota is exceeded, returns early with errors containing quota message.
    """
    # Reset logs for this execution
    reset_execution_logs()

    results = {
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "quota_exceeded": 0,
        "empty_results": 0,
        "still_pending": 0,
        "errors": [],
        "empty_result_jobs": [],
        "saved_files": [],
    }

    # Track job document IDs processed during this execution (for optional log file references)
    processed_job_doc_ids: list[str] = []

    if not settings.information_tracer_api_key:
        results["errors"].append("INFORMATION_TRACER_API_KEY is not configured")
        return results

    # Early return: Check quota before processing jobs
    # If quota is exceeded (400/400), skip processing to avoid wasted API calls
    try:
        from trust_api.scrapping_tools.information_tracer import check_api_usage

        api_usage = check_api_usage(settings.information_tracer_api_key)
        if isinstance(api_usage, dict) and "usage" in api_usage:
            daily_usage = api_usage["usage"].get("day", {})
            searches_used = (
                daily_usage.get("searches_used", 0) if isinstance(daily_usage, dict) else 0
            )
            limits = api_usage.get("limits", {})
            daily_limit = limits.get("max_searches_per_day", 0) if isinstance(limits, dict) else 0

            # Check if quota is exceeded or very close to limit (>= 100%)
            if daily_limit > 0 and searches_used >= daily_limit:
                quota_message = (
                    f"Quota exceeded: {searches_used}/{daily_limit} searches used. "
                    f"Skipping job processing to avoid wasted API calls."
                )
                results["errors"].append(quota_message)
                logger.warning(quota_message)
                # Log this as a quota_exceeded event in execution logs
                add_log_entry(
                    post_id="system",
                    url="https://informationtracer.com/account_stat",
                    success=False,
                    error_message=quota_message,
                    skipped=True,
                )
                return results
    except Exception as e:
        # If quota check fails, log warning but continue processing
        # (better to try processing than to stop everything if quota check fails)
        logger.warning(
            f"Could not check quota before processing jobs: {str(e)}. Continuing anyway."
        )

    try:
        # Query pending jobs
        jobs = query_pending_jobs(max_jobs=max_jobs)
        results["processed"] = len(jobs)

        # Import here to avoid circular dependencies
        from trust_api.scrapping_tools.information_tracer import (
            check_status,
            get_result,
        )

        for index, job in enumerate(jobs):
            job_doc_id = job.get("_doc_id")
            job_id = job.get("job_id")
            post_doc_id = job.get("post_doc_id")
            post_id = job.get("post_id")
            platform = job.get("platform", "unknown")
            country = job.get("country", "unknown")
            candidate_id = job.get("candidate_id", "unknown")
            # Get retry_count from job document (if it exists, indicates a retry)
            current_retry_count = job.get("retry_count", 0)

            # Track this job for optional log file references
            if job_doc_id:
                processed_job_doc_ids.append(job_doc_id)

            if not job_id or not job_doc_id:
                error_msg = f"Job missing required fields: job_id={job_id}, job_doc_id={job_doc_id}"
                results["errors"].append(error_msg)
                results["failed"] += 1
                continue

            try:
                # Update job status to processing
                update_job_status(job_doc_id, "processing")

                # Check job status
                status = check_status(job_id, settings.information_tracer_api_key)

                if status == "finished":
                    # Get results
                    result = get_result(
                        job_id,
                        settings.information_tracer_api_key,
                        platform.lower(),  # type: ignore
                    )

                    if result is None:
                        error_msg = (
                            f"Failed to retrieve results for job_id={job_id}, post_id={post_id}"
                        )
                        # Check if quota is exceeded before marking as failed
                        final_status = "failed"
                        try:
                            from trust_api.scrapping_tools.information_tracer import check_api_usage

                            if settings.information_tracer_api_key:
                                api_usage = check_api_usage(settings.information_tracer_api_key)
                                if isinstance(api_usage, dict) and "usage" in api_usage:
                                    daily_usage = api_usage["usage"].get("day", {})
                                    searches_used = daily_usage.get("searches_used", 0)
                                    limits = api_usage.get("limits", {})
                                    daily_limit = limits.get("max_searches_per_day", 0)

                                    if daily_limit > 0 and searches_used >= daily_limit:
                                        final_status = "quota_exceeded"
                                        error_msg = (
                                            f"Failed to retrieve results (quota exceeded): "
                                            f"searches_used={searches_used}/{daily_limit} "
                                            f"for job_id={job_id}, post_id={post_id}"
                                        )
                                        logger.warning(
                                            f"Job {job_id} marked as quota_exceeded "
                                            f"when result is None (quota: {searches_used}/{daily_limit})"
                                        )
                        except Exception as e:
                            logger.warning(f"Could not check quota when result is None: {str(e)}")

                        results["errors"].append(error_msg)
                        if final_status == "quota_exceeded":
                            results["quota_exceeded"] = results.get("quota_exceeded", 0) + 1
                        else:
                            results["failed"] += 1

                        update_job_status(job_doc_id, final_status)

                        # Log to error logs for both quota_exceeded and failed
                        if final_status in ("quota_exceeded", "failed"):
                            add_error_entry(
                                job_id=job_id,
                                post_id=post_id,
                                platform=platform,
                                country=country,
                                candidate_id=candidate_id,
                                error_type=final_status,
                                error_message=error_msg,
                                job_doc_id=job_doc_id,
                            )
                        continue

                    # Validate that result is not empty before saving
                    if _is_result_empty(result):
                        # Empty result is NOT a technical error - job completed successfully, just no data
                        results["empty_results"] += 1
                        update_job_status(job_doc_id, "empty_result")

                        # Update post status to 'done' when job finishes with empty_result
                        # This marks the post as completed, even if no replies were found
                        if post_doc_id:
                            update_post_status(post_doc_id, "done")

                        # Track empty result job (for reporting, not as error)
                        results["empty_result_jobs"].append(
                            {
                                "job_id": job_id,
                                "post_id": post_id,
                                "platform": platform,
                                "country": country,
                                "candidate_id": candidate_id,
                                "reason": "Result from Information Tracer is empty ([] or empty dict)",
                            }
                        )

                        # Log the empty result in execution logs (for tracking)
                        add_log_entry(
                            post_id=post_id,
                            url=f"https://informationtracer.com/rawdata (job_id:{job_id})",
                            success=False,
                            error_message="Result is empty",
                            job_id=job_id,
                        )
                        # Also save to error logs file (for historical tracking, aunque no sea error técnico)
                        add_error_entry(
                            job_id=job_id,
                            post_id=post_id,
                            platform=platform,
                            country=country,
                            candidate_id=candidate_id,
                            error_type="empty_result",
                            error_message="Result from Information Tracer is empty ([] or empty dict)",
                            job_doc_id=job_doc_id,
                        )
                        continue

                    # Check if file already exists in GCS (indicates a retry)
                    existing_file = read_from_gcs_if_exists(
                        country, platform, candidate_id, post_id
                    )
                    # Detect retry: either file exists in GCS OR retry_count > 0 (e.g., from empty_result)
                    is_retry = existing_file is not None or current_retry_count > 0
                    retry_count = current_retry_count

                    # Prepare metadata for retry information
                    metadata = None
                    if is_retry:
                        # Increment retry_count in job document
                        retry_count = increment_job_retry_count(job_doc_id)
                        # Prepare metadata with retry information
                        now = datetime.now(timezone.utc)
                        metadata = {
                            "is_retry": True,
                            "retry_count": retry_count,
                            "retry_timestamp": now.isoformat(),
                            "previous_file_existed": existing_file is not None,
                        }
                        if existing_file:
                            metadata["older_version"] = (
                                existing_file  # Include the previous version
                            )

                        retry_reason = (
                            "file existed in GCS"
                            if existing_file
                            else "reprocessing from empty_result"
                        )
                        logger.info(
                            f"Retrying job {job_id} (retry #{retry_count}, reason: {retry_reason}). "
                            f"post_id={post_id}"
                        )

                    # Save to GCS (with metadata if it's a retry)
                    gcs_uri = save_to_gcs(
                        result, country, platform, candidate_id, post_id, metadata
                    )
                    results["saved_files"].append(gcs_uri)

                    # Update post status to done
                    if post_doc_id:
                        update_post_status(post_doc_id, "done")

                    # Update job status to done
                    update_job_status(job_doc_id, "done")

                    # Log successful processing (include retry information if applicable)
                    add_log_entry(
                        post_id=post_id,
                        url=f"https://informationtracer.com/rawdata (job_id:{job_id})",
                        success=True,
                        status_code=200,
                        job_id=job_id,
                        is_retry=is_retry,
                        retry_count=retry_count,
                    )

                    results["succeeded"] += 1

                elif status == "failed":
                    # Check if quota is exceeded before marking as failed
                    # If quota is exceeded, mark as quota_exceeded instead of failed
                    final_status = "failed"
                    error_type_for_log = "failed"
                    error_msg = f"Job failed for job_id={job_id}, post_id={post_id}"

                    try:
                        from trust_api.scrapping_tools.information_tracer import check_api_usage

                        if settings.information_tracer_api_key:
                            api_usage = check_api_usage(settings.information_tracer_api_key)
                            if isinstance(api_usage, dict) and "usage" in api_usage:
                                daily_usage = api_usage["usage"].get("day", {})
                                searches_used = daily_usage.get("searches_used", 0)
                                limits = api_usage.get("limits", {})
                                daily_limit = limits.get("max_searches_per_day", 0)

                                # Check if quota is exceeded (used >= limit)
                                if daily_limit > 0 and searches_used >= daily_limit:
                                    final_status = "quota_exceeded"
                                    error_type_for_log = "quota_exceeded"
                                    error_msg = (
                                        f"Job failed due to quota exceeded: "
                                        f"searches_used={searches_used}/{daily_limit} "
                                        f"for job_id={job_id}, post_id={post_id}"
                                    )
                                    logger.warning(
                                        f"Job {job_id} marked as quota_exceeded "
                                        f"(quota: {searches_used}/{daily_limit})"
                                    )
                    except Exception as e:
                        # If quota check fails, log warning but continue with failed status
                        logger.warning(f"Could not check quota when job failed: {str(e)}")

                    results["errors"].append(error_msg)
                    if final_status == "quota_exceeded":
                        results["quota_exceeded"] = results.get("quota_exceeded", 0) + 1
                        results["failed"] = results.get("failed", 0)  # Don't increment failed
                    else:
                        results["failed"] += 1

                    update_job_status(job_doc_id, final_status)

                    # Log to error logs for both quota_exceeded and failed
                    if final_status in ("quota_exceeded", "failed"):
                        add_error_entry(
                            job_id=job_id,
                            post_id=post_id,
                            platform=platform,
                            country=country,
                            candidate_id=candidate_id,
                            error_type=error_type_for_log,
                            error_message=error_msg,
                            job_doc_id=job_doc_id,
                        )

                    # Update post status back to noreplies to allow retry
                    # (but only if there's no other pending/processing job for this post)
                    if post_doc_id:
                        if not has_existing_job_for_post(post_id):
                            update_post_status(post_doc_id, "noreplies")

                elif status == "timeout":
                    # Job is still processing, keep it as pending
                    update_job_status(job_doc_id, "pending")
                    results["still_pending"] += 1

                else:
                    # Unknown status, keep as pending
                    update_job_status(job_doc_id, "pending")
                    results["still_pending"] += 1

            except Exception as e:
                error_msg = f"Error processing job_id={job_id}, post_id={post_id}: {str(e)}"
                results["errors"].append(error_msg)
                # Check if quota is exceeded on exception as well
                final_status = "failed"
                try:
                    from trust_api.scrapping_tools.information_tracer import check_api_usage

                    if settings.information_tracer_api_key:
                        api_usage = check_api_usage(settings.information_tracer_api_key)
                        if isinstance(api_usage, dict) and "usage" in api_usage:
                            daily_usage = api_usage["usage"].get("day", {})
                            searches_used = daily_usage.get("searches_used", 0)
                            limits = api_usage.get("limits", {})
                            daily_limit = limits.get("max_searches_per_day", 0)

                            if daily_limit > 0 and searches_used >= daily_limit:
                                final_status = "quota_exceeded"
                                results["quota_exceeded"] = results.get("quota_exceeded", 0) + 1
                                logger.warning(
                                    f"Exception occurred but quota is exceeded: "
                                    f"{searches_used}/{daily_limit}, marking as quota_exceeded"
                                )
                except Exception:
                    # If quota check fails, continue with failed status
                    pass

                if final_status == "failed":
                    results["failed"] += 1

                # Update job status
                try:
                    update_job_status(job_doc_id, final_status)

                    # Log to error logs for both quota_exceeded and failed
                    if final_status in ("quota_exceeded", "failed"):
                        add_error_entry(
                            job_id=job_id,
                            post_id=post_id,
                            platform=platform,
                            country=country,
                            candidate_id=candidate_id,
                            error_type=final_status,
                            error_message=error_msg,
                            job_doc_id=job_doc_id,
                        )

                    # Update post status back to noreplies to allow retry
                    # (but only if there's no other pending/processing job for this post)
                    if post_doc_id:
                        if not has_existing_job_for_post(post_id):
                            update_post_status(post_doc_id, "noreplies")
                except Exception:
                    pass  # Ignore errors updating status

    finally:
        # Save all logs to GCS at the end of execution
        log_file_uri = save_execution_logs(
            requested_max_posts=max_jobs,
            available_posts=results["processed"],
        )
        if log_file_uri:
            results["log_file"] = log_file_uri

        # Save error logs if there are any
        error_file_uri = save_error_logs(
            execution_type="process-jobs",
            requested_max_items=max_jobs,
            available_items=results["processed"],
        )
        if error_file_uri:
            results["error_log_file"] = error_file_uri

        # Update processed jobs with log file references (optional feature)
        if processed_job_doc_ids:
            update_jobs_with_log_files(
                job_doc_ids=processed_job_doc_ids,
                execution_log_file=log_file_uri,
                error_log_file=error_file_uri,
            )

    return results


def fix_jobs_service(max_jobs: int | None = None) -> dict[str, Any]:
    """
    Fix jobs that are marked as 'done' but have empty JSON files in GCS.
    For each job:
    1. Query jobs with status='done'
    2. Read the JSON file from GCS
    3. If empty, retry fetching from Information Tracer
    4. If still empty, log the issue
    5. If successful, update the file in GCS

    Args:
        max_jobs: Maximum number of jobs to check. If None, checks all done jobs.

    Returns:
        Dictionary with processing results including checked count, fixed count, errors, etc.
    """
    # Reset logs for this execution
    reset_execution_logs()

    results = {
        "checked": 0,
        "empty_found": 0,
        "fixed": 0,
        "still_empty": 0,
        "errors": [],
        "fixed_files": [],
        "empty_jobs": [],
    }

    if not settings.information_tracer_api_key:
        results["errors"].append("INFORMATION_TRACER_API_KEY is not configured")
        return results

    try:
        # Import here to avoid circular dependencies
        from trust_api.scrapping_tools.information_tracer import get_result

        # Query done jobs
        jobs = query_done_jobs(max_jobs=max_jobs)
        results["checked"] = len(jobs)

        for job in jobs:
            job_doc_id = job.get("_doc_id")
            job_id = job.get("job_id")
            post_id = job.get("post_id")
            platform = job.get("platform", "unknown")
            country = job.get("country", "unknown")
            candidate_id = job.get("candidate_id", "unknown")

            if not job_id or not job_doc_id or not post_id:
                error_msg = (
                    f"Job missing required fields: job_id={job_id}, "
                    f"job_doc_id={job_doc_id}, post_id={post_id}"
                )
                results["errors"].append(error_msg)
                continue

            try:
                # Read JSON from GCS
                gcs_data = read_from_gcs_if_exists(
                    country=country,
                    platform=platform,
                    candidate_id=candidate_id,
                    post_id=post_id,
                )

                # Check if file exists and is not empty
                if gcs_data is None:
                    error_msg = f"JSON file not found in GCS for job_id={job_id}, post_id={post_id}"
                    results["errors"].append(error_msg)
                    continue

                if not _is_result_empty(gcs_data):
                    # File exists and is not empty, skip
                    continue

                # File is empty, need to retry
                results["empty_found"] += 1

                # Retry fetching from Information Tracer
                result = get_result(
                    job_id,
                    settings.information_tracer_api_key,
                    platform.lower(),  # type: ignore
                )

                if result is None:
                    error_msg = f"Failed to retrieve results on retry for job_id={job_id}, post_id={post_id}"
                    results["errors"].append(error_msg)
                    results["still_empty"] += 1
                    # Log the empty result in execution logs
                    add_log_entry(
                        post_id=post_id,
                        url=f"https://informationtracer.com/rawdata (job_id:{job_id})",
                        success=False,
                        error_message="Failed to retrieve results on retry",
                        job_id=job_id,
                    )
                    # Also save to error logs file
                    add_error_entry(
                        job_id=job_id,
                        post_id=post_id,
                        platform=platform,
                        country=country,
                        candidate_id=candidate_id,
                        error_type="retry_failed",
                        error_message="Failed to retrieve results from Information Tracer on retry",
                        job_doc_id=job_doc_id,
                    )
                    results["empty_jobs"].append(
                        {
                            "job_id": job_id,
                            "post_id": post_id,
                            "platform": platform,
                        }
                    )
                    continue

                # Check if retry result is still empty
                if _is_result_empty(result):
                    error_msg = (
                        f"Result is still empty after retry for job_id={job_id}, post_id={post_id}"
                    )
                    results["errors"].append(error_msg)
                    results["still_empty"] += 1
                    # Log the empty result in execution logs
                    add_log_entry(
                        post_id=post_id,
                        url=f"https://informationtracer.com/rawdata (job_id:{job_id})",
                        success=False,
                        error_message="Result is still empty after retry",
                        job_id=job_id,
                    )
                    # Also save to error logs file
                    add_error_entry(
                        job_id=job_id,
                        post_id=post_id,
                        platform=platform,
                        country=country,
                        candidate_id=candidate_id,
                        error_type="retry_still_empty",
                        error_message="Result is still empty after retry from Information Tracer",
                        job_doc_id=job_doc_id,
                    )
                    results["empty_jobs"].append(
                        {
                            "job_id": job_id,
                            "post_id": post_id,
                            "platform": platform,
                        }
                    )
                    continue

                # Result is not empty, save to GCS
                gcs_uri = save_to_gcs(result, country, platform, candidate_id, post_id)
                results["fixed_files"].append(gcs_uri)
                results["fixed"] += 1

                # Log successful fix
                add_log_entry(
                    post_id=post_id,
                    url=f"https://informationtracer.com/rawdata (job_id:{job_id})",
                    success=True,
                    status_code=200,
                    job_id=job_id,
                )

            except Exception as e:
                error_msg = f"Error fixing job_id={job_id}, post_id={post_id}: {str(e)}"
                results["errors"].append(error_msg)

    finally:
        # Save all logs to GCS at the end of execution
        log_file_uri = save_execution_logs(
            requested_max_posts=max_jobs,
            available_posts=results["checked"],
        )
        if log_file_uri:
            results["log_file"] = log_file_uri

        # Save error logs if there are any
        error_file_uri = save_error_logs(
            execution_type="fix-jobs",
            requested_max_items=max_jobs,
            available_items=results["checked"],
        )
        if error_file_uri:
            results["error_log_file"] = error_file_uri

    return results


def _get_twitter_schema() -> Any:
    """Get the unified schema for all platforms (Twitter/Instagram)."""
    if not pa:
        return None
    return pa.schema(
        [
            # Ingestion metadata
            ("ingestion_date", pa.date32()),
            ("ingestion_timestamp", pa.timestamp("us", tz="UTC")),
            ("source_file", pa.string()),
            # Post context (from file path)
            ("country", pa.string()),
            ("platform", pa.string()),
            ("candidate_id", pa.string()),
            ("parent_post_id", pa.string()),
            # Reply data
            ("tweet_id", pa.string()),
            ("tweet_url", pa.string()),
            ("created_at", pa.string()),  # Keep as string, parse later if needed
            ("full_text", pa.string()),
            ("lang", pa.string()),
            # Author info
            ("user_id", pa.string()),
            ("user_screen_name", pa.string()),
            ("user_name", pa.string()),
            ("user_followers_count", pa.int64()),
            ("user_friends_count", pa.int64()),
            ("user_verified", pa.bool_()),
            # Engagement metrics
            ("reply_count", pa.int64()),
            ("retweet_count", pa.int64()),
            ("quote_count", pa.int64()),
            ("favorite_count", pa.int64()),
            # Tweet type flags
            ("is_reply", pa.bool_()),
            ("is_retweet", pa.bool_()),
            ("is_quote_status", pa.bool_()),
            # Reply context
            ("in_reply_to_status_id_str", pa.string()),
            ("in_reply_to_user_id_str", pa.string()),
            ("in_reply_to_screen_name", pa.string()),
            # Retweet context
            ("retweeted_status_id_str", pa.string()),
            ("retweeted_status_screen_name", pa.string()),
            # Media
            ("has_media", pa.bool_()),
            ("media_count", pa.int64()),
            # Retry metadata (if present)
            ("is_retry", pa.bool_()),
            ("retry_count", pa.int64()),
        ]
    )


def _parse_gcs_path_for_parquet(blob_name: str) -> dict[str, str]:
    """
    Parse GCS blob path to extract metadata.

    Supports both formats:
    1. raw/{country}/{platform}/{candidate_id}/{post_id}.json (with candidate_id subdirectory)
    2. raw/{country}/{platform}/{post_id}.json (without candidate_id subdirectory)

    For format 2, candidate_id may be extracted from filename or left empty.
    """
    parts = blob_name.replace(".json", "").split("/")

    # Handle both raw/ prefix and direct paths
    if parts[0] == "raw":
        parts = parts[1:]

    # Minimum required: country, platform, post_id (len >= 3)
    if len(parts) >= 4:
        # Format 1: raw/{country}/{platform}/{candidate_id}/{post_id}.json
        return {
            "country": parts[0],
            "platform": parts[1],
            "candidate_id": parts[2],
            "parent_post_id": parts[3],
        }
    elif len(parts) >= 3:
        # Format 2: raw/{country}/{platform}/{post_id}.json
        # Try to extract candidate_id from filename if possible
        filename = parts[-1] if parts else ""
        candidate_id = ""
        # Try to extract candidate_id from filename (e.g., "2512161744_tw_ownpost_hnd01monc")
        # Look for patterns like "hnd01monc" in the filename
        if filename:
            # Simple heuristic: look for lowercase letters followed by digits
            match = re.search(r"([a-z]{3,}\d{2,}[a-z]{3,})", filename.lower())
            if match:
                candidate_id = match.group(1)

        return {
            "country": parts[0],
            "platform": parts[1],
            "candidate_id": candidate_id,
            "parent_post_id": parts[2],
        }
    else:
        # Invalid structure - minimum required parts not found
        return {
            "country": parts[0] if len(parts) > 0 else "",
            "platform": parts[1] if len(parts) > 1 else "",
            "candidate_id": "",
            "parent_post_id": parts[-1] if parts else "",
        }


def _is_retweet(item: dict[str, Any]) -> bool:
    """Check if a tweet is a retweet."""
    if item.get("retweeted_status_id_str") or item.get("retweeted_status_screen_name"):
        return True
    if str(item.get("full_text", "")).startswith("RT @"):
        return True
    if item.get("retweeted") is True and item.get("is_quote_status") is False:
        return True
    return False


def _safe_int(value: Any, default: int = 0) -> int:
    """Safely convert to int."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _safe_str(value: Any, default: str = "") -> str:
    """Safely convert to string."""
    if value is None:
        return default
    return str(value)


def _safe_bool(value: Any, default: bool = False) -> bool:
    """Safely convert to bool."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return bool(value)


def _flatten_twitter_record(
    item: dict[str, Any],
    context: dict[str, str],
    ingestion_ts: datetime,
    source_file: str,
    retry_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Flatten a Twitter reply record into a flat dictionary."""
    user = item.get("user", {}) or {}
    media = item.get("entities", {}).get("media", []) or []

    return {
        # Ingestion metadata
        "ingestion_date": ingestion_ts.date(),
        "ingestion_timestamp": ingestion_ts,
        "source_file": source_file,
        # Post context
        "country": context.get("country", ""),
        "platform": context.get("platform", "twitter"),
        "candidate_id": context.get("candidate_id", ""),
        "parent_post_id": context.get("parent_post_id", ""),
        # Reply data
        "tweet_id": _safe_str(item.get("id_str") or item.get("tweet_id")),
        "tweet_url": _safe_str(item.get("tweet_url")),
        "created_at": _safe_str(item.get("created_at")),
        "full_text": _safe_str(item.get("full_text") or item.get("text")),
        "lang": _safe_str(item.get("lang")),
        # Author info
        "user_id": _safe_str(user.get("id_str") or item.get("user_id_str")),
        "user_screen_name": _safe_str(user.get("screen_name") or item.get("user_screen_name")),
        "user_name": _safe_str(user.get("name") or item.get("user_name")),
        "user_followers_count": _safe_int(user.get("followers_count")),
        "user_friends_count": _safe_int(user.get("friends_count")),
        "user_verified": _safe_bool(user.get("verified")),
        # Engagement metrics
        "reply_count": _safe_int(item.get("reply_count")),
        "retweet_count": _safe_int(item.get("retweet_count")),
        "quote_count": _safe_int(item.get("quote_count")),
        "favorite_count": _safe_int(item.get("favorite_count")),
        # Tweet type flags
        "is_reply": bool(item.get("in_reply_to_status_id_str")),
        "is_retweet": _is_retweet(item),
        "is_quote_status": _safe_bool(item.get("is_quote_status")),
        # Reply context
        "in_reply_to_status_id_str": _safe_str(item.get("in_reply_to_status_id_str")),
        "in_reply_to_user_id_str": _safe_str(item.get("in_reply_to_user_id_str")),
        "in_reply_to_screen_name": _safe_str(item.get("in_reply_to_screen_name")),
        # Retweet context
        "retweeted_status_id_str": _safe_str(item.get("retweeted_status_id_str")),
        "retweeted_status_screen_name": _safe_str(item.get("retweeted_status_screen_name")),
        # Media
        "has_media": len(media) > 0,
        "media_count": len(media),
        # Retry metadata
        "is_retry": retry_metadata.get("is_retry", False) if retry_metadata else False,
        "retry_count": retry_metadata.get("retry_count", 0) if retry_metadata else 0,
    }


def _flatten_instagram_record(
    item: dict[str, Any],
    context: dict[str, str],
    ingestion_ts: datetime,
    source_file: str,
    retry_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Flatten an Instagram comment record into a flat dictionary."""
    user = item.get("user", {}) or item.get("owner", {}) or {}

    return {
        # Ingestion metadata
        "ingestion_date": ingestion_ts.date(),
        "ingestion_timestamp": ingestion_ts,
        "source_file": source_file,
        # Post context
        "country": context.get("country", ""),
        "platform": context.get("platform", "instagram"),
        "candidate_id": context.get("candidate_id", ""),
        "parent_post_id": context.get("parent_post_id", ""),
        # Comment data (using Twitter field names for consistency)
        "tweet_id": _safe_str(item.get("id") or item.get("pk")),
        "tweet_url": "",
        "created_at": _safe_str(item.get("created_at") or item.get("taken_at")),
        "full_text": _safe_str(item.get("text")),
        "lang": "",
        # Author info
        "user_id": _safe_str(user.get("id") or user.get("pk")),
        "user_screen_name": _safe_str(user.get("username")),
        "user_name": _safe_str(user.get("full_name")),
        "user_followers_count": 0,
        "user_friends_count": 0,
        "user_verified": _safe_bool(user.get("is_verified")),
        # Engagement metrics
        "reply_count": _safe_int(item.get("child_comment_count")),
        "retweet_count": 0,
        "quote_count": 0,
        "favorite_count": _safe_int(item.get("like_count") or item.get("comment_like_count")),
        # Tweet type flags
        "is_reply": False,
        "is_retweet": False,
        "is_quote_status": False,
        # Reply context
        "in_reply_to_status_id_str": "",
        "in_reply_to_user_id_str": "",
        "in_reply_to_screen_name": "",
        # Retweet context
        "retweeted_status_id_str": "",
        "retweeted_status_screen_name": "",
        # Media
        "has_media": False,
        "media_count": 0,
        # Retry metadata
        "is_retry": retry_metadata.get("is_retry", False) if retry_metadata else False,
        "retry_count": retry_metadata.get("retry_count", 0) if retry_metadata else 0,
    }


def _process_json_file_for_parquet(
    data: dict[str, Any] | list[Any],
    blob_name: str,
    ingestion_ts: datetime,
) -> tuple[list[dict[str, Any]], str]:
    """Process a JSON file and return flattened records."""
    context = _parse_gcs_path_for_parquet(blob_name)
    platform = context.get("platform", "unknown")

    # Extract retry metadata if present
    retry_metadata = None
    if isinstance(data, dict) and "_metadata" in data:
        retry_metadata = data.get("_metadata")
        data = {k: v for k, v in data.items() if k != "_metadata"}

    # Handle different data structures
    records_list: list[dict[str, Any]] = []

    if isinstance(data, list):
        records_list = data
    elif isinstance(data, dict):
        if "data" in data:
            records_list = data["data"] if isinstance(data["data"], list) else [data["data"]]
        else:
            records_list = [data]

    # Flatten records based on platform
    flattened = []
    for item in records_list:
        if not isinstance(item, dict):
            continue

        if platform == "twitter":
            flattened.append(
                _flatten_twitter_record(item, context, ingestion_ts, blob_name, retry_metadata)
            )
        elif platform == "instagram":
            flattened.append(
                _flatten_instagram_record(item, context, ingestion_ts, blob_name, retry_metadata)
            )
        else:
            # Generic fallback - use Twitter schema
            flattened.append(
                _flatten_twitter_record(item, context, ingestion_ts, blob_name, retry_metadata)
            )

    return flattened, platform


def _get_parquet_max_ingestion_timestamp(
    bucket: storage.Bucket,
    date_str: str,
    platform: str,
) -> datetime | None:
    """
    Get the maximum ingestion_timestamp from existing Parquet file, if it exists.

    This is more accurate than blob.updated because:
    - blob.updated updates every time the Parquet is written (not when data was processed)
    - ingestion_timestamp reflects the actual data timestamp in the Parquet
    - This allows proper incremental loading based on actual data timestamps

    Returns:
        Maximum ingestion_timestamp from Parquet records, or None if file doesn't exist or can't be read
    """
    if not pa or not pq:
        return None

    blob_path = f"marts/replies/ingestion_date={date_str}/platform={platform}/data.parquet"
    blob = bucket.blob(blob_path)

    if not blob.exists():
        return None

    try:
        # Download Parquet file
        parquet_data = blob.download_as_bytes()
        parquet_file = io.BytesIO(parquet_data)
        table = pq.read_table(parquet_file)

        # Get max ingestion_timestamp from the 'ingestion_timestamp' column
        # Try to use PyArrow compute for efficient aggregation, fallback to reading all records
        try:
            import pyarrow.compute as pc

            ingestion_timestamp_col = table.column("ingestion_timestamp")
            if ingestion_timestamp_col is None or len(ingestion_timestamp_col) == 0:
                return None

            # Get max value using PyArrow compute
            max_ts_scalar = pc.max(ingestion_timestamp_col)
            if max_ts_scalar.as_py() is None:
                return None

            # Convert PyArrow timestamp to datetime
            max_ts_dt = max_ts_scalar.as_py()
            if isinstance(max_ts_dt, datetime):
                if max_ts_dt.tzinfo is None:
                    return max_ts_dt.replace(tzinfo=timezone.utc)
                return max_ts_dt
            else:
                # Fallback: if not datetime, try to convert
                logger.warning(
                    f"Max ingestion_timestamp is not datetime type: {type(max_ts_dt)}, value: {max_ts_dt}"
                )
                return None
        except ImportError:
            # Fallback if pyarrow.compute is not available: read all records and find max manually
            logger.debug(
                "pyarrow.compute not available, falling back to reading all records to find max"
            )
        except Exception as compute_error:
            # Fallback if PyArrow compute fails: read all records and find max manually
            logger.warning(
                f"Error using PyArrow compute to get max ingestion_timestamp: {compute_error}. "
                "Falling back to reading all records."
            )

        # Fallback method: read all records and find max manually (used if compute fails or not available)
        records = table.to_pylist()
        if not records:
            return None
        max_ts = None
        for record in records:
            ts = record.get("ingestion_timestamp")
            if ts is None:
                continue
            if isinstance(ts, datetime):
                if max_ts is None or ts > max_ts:
                    max_ts = ts
            elif hasattr(ts, "as_py"):  # PyArrow scalar
                try:
                    ts_dt = ts.as_py()
                    if isinstance(ts_dt, datetime):
                        if max_ts is None or ts_dt > max_ts:
                            max_ts = ts_dt
                except Exception:
                    continue

        if max_ts is None:
            return None
        if max_ts.tzinfo is None:
            return max_ts.replace(tzinfo=timezone.utc)
        return max_ts

    except Exception as e:
        logger.warning(f"Failed to get max ingestion_timestamp for Parquet file {blob_path}: {e}")
        return None


def _read_existing_parquet_from_gcs(
    bucket: storage.Bucket,
    date_str: str,
    platform: str,
) -> tuple[list[dict[str, Any]], datetime | None]:
    """
    Read existing Parquet file from GCS if it exists.

    Returns:
        Tuple of (records, last_modified_timestamp)
    """
    if not pa or not pq:
        return [], None

    blob_path = f"marts/replies/ingestion_date={date_str}/platform={platform}/data.parquet"
    blob = bucket.blob(blob_path)

    if not blob.exists():
        return [], None

    try:
        # Reload to get latest metadata
        blob.reload()
        last_modified = blob.updated

        # Download to memory
        parquet_data = blob.download_as_bytes()
        # Read Parquet from bytes
        import io

        parquet_file = io.BytesIO(parquet_data)
        table = pq.read_table(parquet_file)
        # Convert to list of dicts
        return table.to_pylist(), last_modified
    except Exception as e:
        logger.warning(f"Failed to read existing Parquet file {blob_path}: {e}")
        return [], None


def _write_parquet_to_gcs(
    records: list[dict[str, Any]],
    bucket: storage.Bucket,
    date_str: str,
    platform: str,
) -> str:
    """Write records to Parquet file in GCS."""
    if not pa or not pq:
        raise ValueError("pyarrow is not installed. Install with: poetry add pyarrow")

    if not records:
        return ""

    schema = _get_twitter_schema()
    if not schema:
        raise ValueError("pyarrow is not installed. Install with: poetry add pyarrow")

    # Convert to PyArrow table
    table = pa.Table.from_pylist(records, schema=schema)

    # Write to memory buffer
    import io

    buffer = io.BytesIO()
    pq.write_table(table, buffer, compression="snappy")
    buffer.seek(0)

    # Upload to GCS
    blob_path = f"marts/replies/ingestion_date={date_str}/platform={platform}/data.parquet"
    blob = bucket.blob(blob_path)
    blob.upload_from_file(buffer, content_type="application/octet-stream")

    return f"gs://{settings.gcs_bucket_name}/{blob_path}"


def json_to_parquet_service(
    country: str | None = None,
    platform: str | None = None,
    candidate_id: str | None = None,
    skip_timestamp_filter: bool = False,
) -> dict[str, Any]:
    """
    Convert JSON files from GCS raw layer to Parquet format with incremental loading.

    This service:
    1. Reads JSON files from GCS raw layer (raw/{country}/{platform}/...)
    2. Flattens nested structures into tabular format
    3. Groups by ingestion_date and platform
    4. For each partition, reads existing Parquet if it exists and merges with new data
    5. Writes updated Parquet files to GCS marts layer (marts/replies/)

    Args:
        country: Country name to filter (e.g., 'honduras'). If None, processes all countries.
        platform: Platform name to filter (e.g., 'twitter', 'instagram'). If None, processes all platforms.
        candidate_id: Candidate ID to filter. If None, processes all candidates.
        skip_timestamp_filter: If True, processes all JSONs regardless of timestamp (relies on deduplication).
                              If False, uses timestamp-based optimization to skip already-processed JSONs.

    Returns:
        Dictionary with processing results including records processed, files written, etc.
    """
    print(
        f"[JSON-TO-PARQUET-SERVICE] Starting with filters: country={country}, platform={platform}, "
        f"candidate_id={candidate_id}, skip_timestamp_filter={skip_timestamp_filter}"
    )
    logger.info(
        f"Starting json_to_parquet_service with filters: country={country}, platform={platform}, "
        f"candidate_id={candidate_id}, skip_timestamp_filter={skip_timestamp_filter}"
    )

    if not pa or not pq:
        print("[JSON-TO-PARQUET-SERVICE] ERROR: pyarrow is not installed")
        logger.error("pyarrow is not installed")
        return {
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "errors": ["pyarrow is not installed. Install with: poetry add pyarrow"],
            "written_files": [],
        }

    if not settings.gcs_bucket_name:
        print("[JSON-TO-PARQUET-SERVICE] ERROR: GCS_BUCKET_NAME is not configured")
        logger.error("GCS_BUCKET_NAME is not configured")
        return {
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "errors": ["GCS_BUCKET_NAME is not configured"],
            "written_files": [],
        }

    print(f"[JSON-TO-PARQUET-SERVICE] Using GCS bucket: {settings.gcs_bucket_name}")
    logger.info(f"Using GCS bucket: {settings.gcs_bucket_name}")

    results = {
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "errors": [],
        "written_files": [],
    }

    try:
        client = get_gcs_client()
        bucket = client.bucket(settings.gcs_bucket_name)

        # Build prefix for filtering
        prefix = "raw"
        if country:
            prefix = f"{prefix}/{country}"
            if platform:
                prefix = f"{prefix}/{platform}"

        # OPTIMIZATION: Incremental loading - only process JSONs newer than max ingestion_timestamp in Parquet
        # Strategy: Compare JSON ingestion_ts with MAX(ingestion_timestamp) from Parquet records
        # - Use MAX(ingestion_timestamp) from Parquet records (not blob.updated) for accurate filtering
        # - blob.updated updates every time Parquet is written, but ingestion_timestamp reflects actual data
        # - Lazy-load max timestamps only when needed (when we encounter JSONs for that partition)
        # - Deduplication by (source_file, tweet_id) ensures no duplicates as final safety net

        # Get Parquet max ingestion_timestamps per partition (lazy-loaded when needed)
        # Key: (date_str, platform) -> Value: max ingestion_timestamp from Parquet records (or None if can't read)
        parquet_file_timestamps: dict[tuple[str, str], datetime | None] = {}

        if skip_timestamp_filter:
            logger.info(
                "Timestamp filter disabled - will process all JSONs (deduplication will handle duplicates)"
            )
        else:
            logger.info(
                "Timestamp filter enabled - will skip JSONs older than Parquet max ingestion_timestamp (incremental loading)"
            )

        # For incremental loading, we need to know the max ingestion_timestamp per partition
        # We'll use lazy loading: only read Parquet files when we encounter JSONs for that partition
        # This avoids reading all Parquet files upfront (expensive) but still provides accurate filtering
        parquet_prefix = "marts/replies/ingestion_date="
        print(f"[JSON-TO-PARQUET-SERVICE] Listing Parquet files with prefix: {parquet_prefix}")
        parquet_blobs = bucket.list_blobs(prefix=parquet_prefix)
        print("[JSON-TO-PARQUET-SERVICE] Starting iteration over Parquet blobs...")

        # Build a set of existing partitions (for quick lookup without reading content)
        existing_partitions: set[tuple[str, str]] = set()
        blob_count = 0
        for parquet_blob in parquet_blobs:
            blob_count += 1
            if blob_count % 10 == 0:
                print(f"[JSON-TO-PARQUET-SERVICE] Processed {blob_count} Parquet blobs so far...")

            if not parquet_blob.name.endswith(".parquet"):
                continue
            parts = parquet_blob.name.split("/")
            if len(parts) >= 4:
                date_part = parts[2].replace("ingestion_date=", "")
                platform_part = parts[3].replace("platform=", "")

                if platform and platform_part != platform:
                    continue

                existing_partitions.add((date_part, platform_part))

        print(
            f"[JSON-TO-PARQUET-SERVICE] Finished listing {blob_count} Parquet blobs. "
            f"Found {len(existing_partitions)} unique partitions: {list(existing_partitions)}"
        )
        logger.info(
            f"Found {len(existing_partitions)} Parquet partitions (will lazy-load max timestamps when needed)"
        )

        # Process JSONs: only download content for those newer than Parquet
        print(f"[JSON-TO-PARQUET-SERVICE] Starting to process JSONs from prefix: {prefix}")
        json_files = []
        skipped_count = 0
        total_json_blobs = 0
        blobs = bucket.list_blobs(prefix=prefix)
        print("[JSON-TO-PARQUET-SERVICE] Starting iteration over JSON blobs...")

        json_count = 0
        for blob in blobs:
            json_count += 1
            if json_count % 50 == 0:
                print(
                    f"[JSON-TO-PARQUET-SERVICE] Iterated {json_count} blobs so far... "
                    f"(json_files={total_json_blobs}, skipped={skipped_count}, queued_for_processing={len(json_files)})"
                )

            if not blob.name.lower().endswith(".json"):
                continue

            total_json_blobs += 1
            parts = blob.name.split("/")
            path_parts = parts[1:] if parts[0] == "raw" else parts

            # Accept both structures:
            # 1. raw/{country}/{platform}/{candidate_id}/{post_id}.json (len >= 4)
            # 2. raw/{country}/{platform}/{post_id}.json (len == 3)
            # Minimum required: country, platform, post_id (len >= 3)
            if len(path_parts) < 3:
                logger.debug(
                    f"Skipping {blob.name}: Invalid structure (requires at least country/platform/post_id)"
                )
                continue

            # Apply candidate_id filter if specified
            if candidate_id:
                # Check if candidate_id is in the path (could be subdirectory or in filename)
                if candidate_id not in parts:
                    # Also check if candidate_id might be in the filename
                    filename = parts[-1] if parts else ""
                    if candidate_id not in filename:
                        continue

            try:
                # Get metadata only (blob.reload() reads headers, not content - lightweight)
                if total_json_blobs <= 5:  # Log first few for debugging
                    print(
                        f"[JSON-TO-PARQUET-SERVICE] Processing JSON blob {total_json_blobs}: {blob.name}"
                    )
                blob.reload()
                ingestion_ts = blob.updated or datetime.now(timezone.utc)
                if ingestion_ts.tzinfo is None:
                    ingestion_ts = ingestion_ts.replace(tzinfo=timezone.utc)

                # Determine partition based on ingestion date
                date_str = ingestion_ts.strftime("%Y-%m-%d")
                # Platform is always at index 1: raw/{country}/{platform}/...
                platform_from_path = path_parts[1] if len(path_parts) > 1 else ""
                partition_key = (date_str, platform_from_path)

                # Incremental loading: Use MAX(ingestion_timestamp) from Parquet records (not blob.updated)
                # This is more accurate because blob.updated updates every time Parquet is written,
                # but ingestion_timestamp reflects the actual data timestamps
                if not skip_timestamp_filter and partition_key in existing_partitions:
                    # Lazy-load max ingestion_timestamp for this partition if not already cached
                    if partition_key not in parquet_file_timestamps:
                        max_ts = _get_parquet_max_ingestion_timestamp(
                            bucket, date_str, platform_from_path
                        )
                        if max_ts is not None:
                            parquet_file_timestamps[partition_key] = max_ts
                            logger.info(
                                f"Loaded max ingestion_timestamp {max_ts} for partition {partition_key} "
                                f"(will skip JSONs more than 5 minutes older)"
                            )
                        else:
                            # Parquet exists but couldn't read it - skip filtering for this partition
                            logger.warning(
                                f"Could not read max ingestion_timestamp for partition {partition_key}, will process all JSONs"
                            )
                            parquet_file_timestamps[partition_key] = (
                                None  # Mark as tried but failed
                            )

                    # Check if we have a valid max timestamp for comparison
                    if (
                        partition_key in parquet_file_timestamps
                        and parquet_file_timestamps[partition_key] is not None
                    ):
                        parquet_max_ts = parquet_file_timestamps[partition_key]
                        # Use a small buffer (5 minutes) to handle edge cases, but be more lenient
                        # The buffer prevents skipping JSONs that were written just before the Parquet was updated
                        buffer = timedelta(minutes=5)
                        # Only skip if JSON ingestion_ts is clearly older (more than buffer) than max ingestion_timestamp in Parquet
                        # This means the Parquet already contains data from this JSON or newer JSONs
                        # But we need to be careful: if ingestion_ts == parquet_max_ts (same timestamp), we should still process
                        # because the JSON might have been updated or we might need to reprocess
                        if ingestion_ts < (parquet_max_ts - buffer):
                            logger.info(
                                f"Skipping {blob.name}: JSON ingestion_ts {ingestion_ts} is more than 5 minutes older than "
                                f"Parquet max ingestion_timestamp {parquet_max_ts} for partition {partition_key}"
                            )
                            skipped_count += 1
                            continue
                        # JSON is recent enough (within 5 minutes of max or newer) → will process
                        # This includes JSONs with timestamp equal to or newer than max, and those within 5 minutes
                        logger.debug(
                            f"Processing {blob.name}: JSON ingestion_ts {ingestion_ts} is within 5 minutes of or newer than "
                            f"Parquet max ingestion_timestamp {parquet_max_ts} for partition {partition_key}"
                        )
                    # If parquet_file_timestamps[partition_key] is None, we couldn't read it, so process all JSONs
                elif skip_timestamp_filter:
                    logger.debug(
                        f"Processing {blob.name} (timestamp filter disabled) for partition {partition_key}"
                    )

                # Download JSON content only if it needs processing
                raw = blob.download_as_text(encoding="utf-8")
                data = json.loads(raw)
                json_files.append((blob.name, data, ingestion_ts))
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON in {blob.name}: {e}")
                results["errors"].append(f"Invalid JSON in {blob.name}: {e}")
                continue
            except Exception as e:
                logger.error(f"Error reading {blob.name}: {e}")
                results["errors"].append(f"Error reading {blob.name}: {e}")
                continue

        print(
            f"[JSON-TO-PARQUET-SERVICE] Finished processing JSONs. "
            f"Total found: {total_json_blobs}, Skipped: {skipped_count}, To process: {len(json_files)}"
        )
        logger.info(
            f"Total JSON blobs found: {total_json_blobs}, "
            f"Skipped (older than Parquet max - 5min): {skipped_count}, "
            f"To process: {len(json_files)}"
        )

        if skipped_count > 0:
            logger.info(
                f"Skipped {skipped_count} JSON files (more than 5 minutes older than Parquet max ingestion_timestamp). "
                f"If new JSONs are not being processed, use skip_timestamp_filter=true to bypass this filter."
            )

        results["processed"] = len(json_files)

        if not json_files:
            print("[JSON-TO-PARQUET-SERVICE] No JSON files to process. Returning early.")
            return results

        print(f"[JSON-TO-PARQUET-SERVICE] Grouping {len(json_files)} JSON files by partition...")
        # Group records by ingestion date and platform
        records_by_partition: dict[tuple[str, str], list[dict[str, Any]]] = {}

        for blob_name, data, ingestion_ts in json_files:
            try:
                flattened, platform = _process_json_file_for_parquet(data, blob_name, ingestion_ts)

                if not flattened:
                    continue

                # Partition key: (ingestion_date, platform)
                date_str = ingestion_ts.strftime("%Y-%m-%d")
                key = (date_str, platform)

                if key not in records_by_partition:
                    records_by_partition[key] = []
                records_by_partition[key].extend(flattened)
            except Exception as e:
                logger.error(f"Error processing {blob_name}: {e}")
                results["errors"].append(f"Error processing {blob_name}: {e}")
                results["failed"] += 1
                continue

        print(
            f"[JSON-TO-PARQUET-SERVICE] Found {len(records_by_partition)} partitions to write: {list(records_by_partition.keys())}"
        )
        print("[JSON-TO-PARQUET-SERVICE] Starting to write Parquet files...")
        # Write Parquet files with incremental loading
        partition_count = 0
        for (date_str, platform), new_records in records_by_partition.items():
            partition_count += 1
            print(
                f"[JSON-TO-PARQUET-SERVICE] Writing partition {partition_count}/{len(records_by_partition)}: {date_str}/{platform} ({len(new_records)} records)"
            )
            try:
                # Read existing Parquet if it exists (returns records and timestamp)
                existing_records, _ = _read_existing_parquet_from_gcs(bucket, date_str, platform)

                # Merge records: combine existing and new, deduplicate by source_file + tweet_id
                if existing_records:
                    # Create a set of existing record keys for deduplication
                    existing_keys = {
                        (r.get("source_file", ""), r.get("tweet_id", "")) for r in existing_records
                    }

                    # Add only new records that don't already exist
                    new_count = 0
                    for record in new_records:
                        key = (record.get("source_file", ""), record.get("tweet_id", ""))
                        if key not in existing_keys:
                            existing_records.append(record)
                            existing_keys.add(key)
                            new_count += 1

                    all_records = existing_records
                    logger.info(
                        f"Merged {new_count} new records into existing {len(existing_records) - new_count} "
                        f"records for {date_str}/{platform}"
                    )
                else:
                    all_records = new_records
                    logger.info(
                        f"Created new Parquet file with {len(new_records)} records for {date_str}/{platform}"
                    )

                # Write merged Parquet file
                gcs_uri = _write_parquet_to_gcs(all_records, bucket, date_str, platform)
                if gcs_uri:
                    results["written_files"].append(gcs_uri)
                    results["succeeded"] += 1
                    logger.info(f"Wrote {len(all_records)} total records to {gcs_uri}")
            except Exception as e:
                logger.error(f"Error writing Parquet for {date_str}/{platform}: {e}")
                results["errors"].append(f"Error writing Parquet for {date_str}/{platform}: {e}")
                results["failed"] += 1

    except Exception as e:
        print(f"[JSON-TO-PARQUET-SERVICE] ERROR: {e}")
        logger.error(f"Error in json_to_parquet_service: {e}")
        results["errors"].append(f"Error in json_to_parquet_service: {e}")

    print(
        f"[JSON-TO-PARQUET-SERVICE] Completed. Processed: {results['processed']}, "
        f"Succeeded: {results['succeeded']}, Failed: {results['failed']}, "
        f"Files written: {len(results['written_files'])}"
    )
    return results
