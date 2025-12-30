from typing import Literal

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

from trust_api.scrapping_tools.core.config import settings
from trust_api.scrapping_tools.services import (
    fetch_post_information,
    fix_jobs_service,
    process_pending_jobs_service,
    process_posts_service,
    query_pending_jobs,
)


class PostInformationRequest(BaseModel):
    post_id: str
    platform: str
    max_posts: int = 100


class PostInformationResponse(BaseModel):
    post_id: str
    data: dict


class ProcessPostsResponse(BaseModel):
    processed: int
    succeeded: int
    failed: int
    skipped: int
    errors: list[str]
    jobs_created: list[dict]  # List of jobs created with job_id, job_doc_id, post_id
    log_file: str | None = None  # GCS URI of the execution log file
    error_log_file: str | None = None  # GCS URI of the error log file (for submit failures, etc.)


class ProcessJobsResponse(BaseModel):
    processed: int
    succeeded: int
    failed: int
    still_pending: int
    errors: list[str]
    saved_files: list[str]
    log_file: str | None = None  # GCS URI of the execution log file
    error_log_file: str | None = None  # GCS URI of the error log file (for empty results)


class PendingJobsResponse(BaseModel):
    total: int
    jobs: list[dict]  # List of pending jobs with job_id, post_id, platform, etc.


class FixJobsResponse(BaseModel):
    checked: int
    empty_found: int
    fixed: int
    still_empty: int
    errors: list[str]
    fixed_files: list[str]
    empty_jobs: list[dict]  # List of jobs that are still empty after retry
    log_file: str | None = None  # GCS URI of the execution log file
    error_log_file: str | None = None  # GCS URI of the error log file (for empty results)


app = FastAPI(
    title="Scrapping Tools Service",
    description="Service for fetching post information from external sources",
    version=settings.version,
)


@app.get("/")
async def root():
    return {
        "service": settings.service_name,
        "version": settings.version,
        "docs": "/docs",
        "environment": settings.environment,
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.post("/posts/information", response_model=PostInformationResponse)
async def get_post_information(request: PostInformationRequest):
    """
    Fetch post information from the external Information Tracer service.

    Args:
        request: Request containing post_id

    Returns:
        PostInformationResponse with post_id and fetched data

    Raises:
        HTTPException: If the request fails or configuration is missing
    """
    try:
        data = fetch_post_information(
            post_id=request.post_id,
            platform=request.platform,
            max_posts=request.max_posts,
        )
        return PostInformationResponse(post_id=request.post_id, data=data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid request: {str(e)}",
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Information Tracer service error: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching post information: {str(e)}",
        )


@app.post("/process-posts", response_model=ProcessPostsResponse)
async def process_posts_endpoint(
    max_posts: int | None = None,
    sort_by: Literal["time", "engagement"] = "time",
):
    """
    Submit jobs to Information Tracer API for posts with status='noreplies'.

    This endpoint:
    1. Queries Firestore collection 'posts' for documents with status='noreplies'
       - Posts are prioritized by platform: Twitter posts are processed first
       - Within each platform, posts are ordered by created_at (oldest first)
    2. For each post, submits a job to Information Tracer API (does not wait for completion)
    3. Saves the job ID (hash_id) to the 'pending_jobs' collection in Firestore

    This is a fast operation that only submits jobs. To retrieve results, use /process-jobs endpoint.

    Args:
        max_posts: Maximum number of posts to process in this call. If None, processes all posts with status='noreplies'.
                   When max_posts is specified, Twitter posts are prioritized (e.g., if max_posts=30 and there are
                   30+ Twitter posts, all 30 will be Twitter posts).
        sort_by: Sort order for replies ('time' or 'engagement'). Default is 'time'.
                 Note: Only applies to keyword search, not account search.

    Returns:
        ProcessPostsResponse with processing results including jobs created, errors, etc.

    Raises:
        HTTPException: If the processing fails or configuration is missing
    """
    try:
        results = process_posts_service(max_posts=max_posts, sort_by=sort_by)
        return ProcessPostsResponse(**results)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing posts: {str(e)}",
        )


@app.get("/pending-jobs", response_model=PendingJobsResponse)
async def get_pending_jobs_endpoint(max_jobs: int | None = None):
    """
    Query pending jobs from Firestore 'pending_jobs' collection without processing them.

    This endpoint only lists the pending jobs, it does not process them.
    To process jobs, use /process-jobs endpoint.

    Args:
        max_jobs: Maximum number of jobs to return. If None, returns all pending jobs.

    Returns:
        PendingJobsResponse with list of pending jobs and total count.

    Raises:
        HTTPException: If the query fails or configuration is missing
    """
    try:
        jobs = query_pending_jobs(max_jobs=max_jobs)
        # Remove internal _doc_id field from response (keep it internal)
        jobs_clean = []
        for job in jobs:
            job_copy = {k: v for k, v in job.items() if k != "_doc_id"}
            jobs_clean.append(job_copy)
        return PendingJobsResponse(total=len(jobs_clean), jobs=jobs_clean)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error querying pending jobs: {str(e)}",
        )


@app.post("/process-jobs", response_model=ProcessJobsResponse)
async def process_jobs_endpoint(max_jobs: int | None = None):
    """
    Process pending jobs from Firestore 'pending_jobs' collection.

    This endpoint:
    1. Queries Firestore collection 'pending_jobs' for documents with status='pending'
    2. For each job, checks the status with Information Tracer API
    3. If the job is finished, retrieves the results
    4. Saves the JSON response to GCS bucket with structure:
       country/platform/candidate_id/{post_id}.json
    5. Updates the post status to 'done' in Firestore after successful save
    6. Updates the job status to 'done' in Firestore

    Args:
        max_jobs: Maximum number of jobs to process in this call. If None, processes all pending jobs.

    Returns:
        ProcessJobsResponse with processing results including success count, errors, saved files, etc.

    Raises:
        HTTPException: If the processing fails or configuration is missing
    """
    try:
        results = process_pending_jobs_service(max_jobs=max_jobs)
        return ProcessJobsResponse(**results)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing jobs: {str(e)}",
        )


@app.post("/fix-jobs", response_model=FixJobsResponse)
async def fix_jobs_endpoint(max_jobs: int | None = None):
    """
    Fix jobs that are marked as 'done' but have empty JSON files in GCS.

    This endpoint:
    1. Queries Firestore collection 'pending_jobs' for documents with status='done'
    2. For each job, reads the JSON file from GCS
    3. If the file is empty, retries fetching from Information Tracer API
    4. If the result is still empty, logs the issue
    5. If successful, updates the file in GCS

    Args:
        max_jobs: Maximum number of jobs to check. If None, checks all done jobs.

    Returns:
        FixJobsResponse with processing results including checked count, fixed count, errors, etc.

    Raises:
        HTTPException: If the processing fails or configuration is missing
    """
    try:
        results = fix_jobs_service(max_jobs=max_jobs)
        return FixJobsResponse(**results)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fixing jobs: {str(e)}",
        )
