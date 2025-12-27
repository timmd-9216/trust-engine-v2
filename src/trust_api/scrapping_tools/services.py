"""Services for scrapping-tools."""

import json
from typing import Any

import httpx
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


def query_posts_without_replies() -> list[dict[str, Any]]:
    """
    Query Firestore for posts with status='noreplies'.

    Returns:
        List of post documents with fields: post_id, country, platform, candidate_id, etc.
    """
    client = get_firestore_client()
    query = client.collection(settings.firestore_collection).where("status", "==", "noreplies")

    posts = []
    for doc in query.stream():
        doc_data = doc.to_dict()
        posts.append(doc_data)

    return posts


def fetch_post_information(post_id: str) -> dict[str, Any]:
    """
    Query external information tracer service for a given post_id.

    Args:
        post_id: The post ID to query

    Returns:
        JSON response from the external service

    Raises:
        ValueError: If INFORMATION_TRACER_URL or INFORMATION_TRACER_TOKEN is not configured
        httpx.HTTPStatusError: If the request fails
    """
    if not settings.information_tracer_url:
        raise ValueError("INFORMATION_TRACER_URL is not configured")
    if not settings.information_tracer_token:
        raise ValueError("INFORMATION_TRACER_TOKEN is not configured")

    # Construct URL: append /posts/{post_id} to the base URL
    base_url = settings.information_tracer_url.rstrip("/")
    url = f"{base_url}/posts/{post_id}"
    headers = {
        "Authorization": f"Bearer {settings.information_tracer_token}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()


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

    # Create path: country/platform/candidate_id/{post_id}.json
    # Normalize path components to avoid issues with special characters
    safe_country = country.replace("/", "_").replace("\\", "_")
    safe_platform = platform.replace("/", "_").replace("\\", "_")
    safe_candidate_id = str(candidate_id).replace("/", "_").replace("\\", "_")
    safe_post_id = str(post_id).replace("/", "_").replace("\\", "_")

    blob_path = f"{safe_country}/{safe_platform}/{safe_candidate_id}/{safe_post_id}.json"

    blob = bucket.blob(blob_path)
    blob.upload_from_string(
        json.dumps(data, ensure_ascii=False, indent=2),
        content_type="application/json",
    )

    return f"gs://{settings.gcs_bucket_name}/{blob_path}"


def process_posts_service() -> dict[str, Any]:
    """
    Main processing function that:
    1. Queries Firestore for posts with status='noreplies'
    2. For each post, queries the external Information Tracer service
    3. Saves the results to GCS

    Returns:
        Dictionary with processing results including success count, errors, etc.
    """
    results = {
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "errors": [],
        "saved_files": [],
    }

    # Query posts without replies
    posts = query_posts_without_replies()
    results["processed"] = len(posts)

    for post in posts:
        post_id = post.get("post_id")
        if not post_id:
            error_msg = f"Post missing post_id field: {post.get('id', 'unknown')}"
            results["errors"].append(error_msg)
            results["failed"] += 1
            continue

        country = post.get("country", "unknown")
        platform = post.get("platform", "unknown")
        candidate_id = post.get("candidate_id", "unknown")

        try:
            # Fetch information from Information Tracer service
            info_data = fetch_post_information(post_id)

            # Save to GCS
            gcs_uri = save_to_gcs(info_data, country, platform, candidate_id, post_id)
            results["saved_files"].append(gcs_uri)
            results["succeeded"] += 1

        except Exception as e:
            error_msg = f"Error processing post_id={post_id}: {str(e)}"
            results["errors"].append(error_msg)
            results["failed"] += 1

    return results
