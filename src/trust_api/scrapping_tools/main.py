from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi import status as http_status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from trust_api.scrapping_tools.core.config import settings
from trust_api.scrapping_tools.services import (
    count_empty_result_jobs,
    count_jobs_by_status,
    count_posts_by_status,
    fetch_post_information,
    fix_jobs_service,
    json_to_parquet_service,
    process_pending_jobs_service,
    process_posts_service,
    query_pending_jobs,
    retry_empty_result_jobs_service,
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
    failed: int  # Solo errores técnicos reales (API failures, excepciones, etc.)
    empty_results: int  # Jobs terminados exitosamente pero sin datos útiles (no es error técnico)
    still_pending: int
    errors: list[str]  # Solo errores técnicos (no incluye empty_results)
    empty_result_jobs: list[dict]  # Lista de jobs con resultado vacío (info, no error)
    saved_files: list[str]
    log_file: str | None = None  # GCS URI of the execution log file
    error_log_file: str | None = (
        None  # GCS URI of the error log file (para empty_results y errores técnicos)
    )


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


class JsonToParquetResponse(BaseModel):
    processed: int
    succeeded: int
    failed: int
    errors: list[str]
    written_files: list[str]  # List of GCS URIs of written Parquet files


class EmptyResultJobsResponse(BaseModel):
    count: int
    filters: dict[str, str | None]  # Applied filters (candidate_id, platform, country)


class JobsCountResponse(BaseModel):
    count: int
    status: str  # Job status that was counted
    filters: dict[
        str, str | bool | None
    ]  # Applied filters (candidate_id, platform, country, updated_today)


class PostsCountResponse(BaseModel):
    count: int
    status: str  # Post status that was counted
    filters: dict[
        str, str | bool | None
    ]  # Applied filters (candidate_id, platform, country, updated_today)


class RetryEmptyResultJobsResponse(BaseModel):
    total_found: int
    retried: int
    errors: list[str]
    retried_jobs: list[dict]


class QuotaResponse(BaseModel):
    usage: dict | None = None
    limits: dict | None = None
    daily_used: int | None = None
    daily_limit: int | None = None
    percentage: float | None = None
    status: str  # "ok", "warning", "exceeded", "error"
    message: str | None = None  # List of retried jobs with details


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
        "dashboard": "/dashboard",
        "environment": settings.environment,
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """
    Dashboard web para visualizar KPIs del sistema.

    Muestra:
    - Posts pendientes de extraer (status="noreplies")
    - Contador de empty jobs

    El dashboard se actualiza automáticamente cada 30 segundos.
    """
    dashboard_path = Path(__file__).parent / "dashboard.html"
    if not dashboard_path.exists():
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Dashboard HTML file not found",
        )
    with open(dashboard_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content)


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
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid request: {str(e)}",
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=http_status.HTTP_502_BAD_GATEWAY,
            detail=f"Information Tracer service error: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
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
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
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
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error querying pending jobs: {str(e)}",
        )


@app.post("/process-jobs", response_model=ProcessJobsResponse)
async def process_jobs_endpoint(max_jobs: int | None = None):
    """
    Process pending jobs from Firestore 'pending_jobs' collection.

    This endpoint:
    0. **Checks Information Tracer API quota before processing** - If quota is exceeded (400/400),
       returns early without processing any jobs to avoid wasted API calls
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
        ProcessJobsResponse with processing results:
        - succeeded: Jobs with useful data saved successfully
        - empty_results: Jobs completed successfully but returned empty data (NOT a technical error)
        - failed: Only actual technical errors (API failures, exceptions, etc.)
        - errors: List of technical error messages (includes quota exceeded message if applicable)
        - empty_result_jobs: List of jobs with empty results (for monitoring, not errors)

    Note:
        Empty results are distinguished from technical errors:
        - Empty result: Job completed successfully in Information Tracer but returned no data
        - Technical error: API failure, exception, or job failed in Information Tracer

        If quota is exceeded (400/400 searches used), the endpoint will return early with:
        - processed: 0
        - succeeded: 0
        - errors: ["Quota exceeded: 400/400 searches used. Skipping job processing..."]

    Raises:
        HTTPException: If the processing fails or configuration is missing
    """
    try:
        results = process_pending_jobs_service(max_jobs=max_jobs)
        return ProcessJobsResponse(**results)
    except Exception as e:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
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
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fixing jobs: {str(e)}",
        )


@app.get("/empty-result-jobs/count", response_model=EmptyResultJobsResponse)
async def count_empty_result_jobs_endpoint(
    candidate_id: str | None = None,
    platform: str | None = None,
    country: str | None = None,
):
    """
    Count jobs with status='empty_result' in Firestore.

    This endpoint allows querying the count of jobs that have empty results.
    Useful for monitoring and deciding when to retry jobs.

    Args:
        candidate_id: Optional candidate_id to filter jobs
        platform: Optional platform to filter jobs (e.g., 'twitter', 'instagram')
        country: Optional country to filter jobs

    Returns:
        EmptyResultJobsResponse with count and applied filters.

    Raises:
        HTTPException: If the query fails or configuration is missing
    """
    try:
        count = count_empty_result_jobs(
            candidate_id=candidate_id,
            platform=platform,
            country=country,
        )
        return EmptyResultJobsResponse(
            count=count,
            filters={
                "candidate_id": candidate_id,
                "platform": platform,
                "country": country,
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error counting empty result jobs: {str(e)}",
        )


@app.get("/jobs/count", response_model=JobsCountResponse)
async def count_jobs_by_status_endpoint(
    status: str = "pending",
    candidate_id: str | None = None,
    platform: str | None = None,
    country: str | None = None,
    updated_today: bool = False,
):
    """
    Count jobs with a specific status in Firestore.

    This endpoint allows querying the count of jobs by status (pending, empty_result, done, failed, etc.)
    with optional filters. Useful for monitoring job states.

    Args:
        status: Job status to count. Default is 'pending'. Valid values: 'pending', 'empty_result', 'done', 'failed', 'processing', 'verified'
        candidate_id: Optional candidate_id to filter jobs
        platform: Optional platform to filter jobs (e.g., 'twitter', 'instagram')
        country: Optional country to filter jobs
        updated_today: If True, only count jobs updated today (default: False)

    Returns:
        JobsCountResponse with count, status, and applied filters.

    Raises:
        HTTPException: If the query fails or configuration is missing

    Examples:
        # Count pending jobs
        GET /jobs/count?status=pending

        # Count pending jobs for a specific candidate
        GET /jobs/count?status=pending&candidate_id=hnd09sosa

        # Count empty_result jobs (same as /empty-result-jobs/count)
        GET /jobs/count?status=empty_result

        # Count done jobs
        GET /jobs/count?status=done

        # Count jobs updated today
        GET /jobs/count?status=done&updated_today=true
    """
    try:
        count = count_jobs_by_status(
            status=status,
            candidate_id=candidate_id,
            platform=platform,
            country=country,
            updated_today=updated_today,
        )
        return JobsCountResponse(
            count=count,
            status=status,
            filters={
                "candidate_id": candidate_id,
                "platform": platform,
                "country": country,
                "updated_today": updated_today,
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error counting jobs by status: {str(e)}",
        ) from None


@app.get("/api/quota", response_model=QuotaResponse)
async def get_quota_status():
    """
    Get Information Tracer API quota/usage status.

    Returns:
        QuotaResponse with usage information, limits, and status indicators.
    """
    try:
        from trust_api.scrapping_tools.information_tracer import check_api_usage

        if not settings.information_tracer_api_key:
            return QuotaResponse(
                usage=None,
                limits=None,
                daily_used=None,
                daily_limit=None,
                percentage=None,
                status="error",
                message="INFORMATION_TRACER_API_KEY is not configured",
            )

        api_usage = check_api_usage(settings.information_tracer_api_key)

        if not isinstance(api_usage, dict):
            return QuotaResponse(
                usage=None,
                limits=None,
                daily_used=None,
                daily_limit=None,
                percentage=None,
                status="error",
                message="Invalid API usage response format",
            )

        # Extract usage and limits
        usage = api_usage.get("usage", {})
        limits = api_usage.get("limits", {})
        daily_usage = usage.get("day", {}) if isinstance(usage, dict) else {}
        daily_used_raw = daily_usage.get("searches_used", 0) if isinstance(daily_usage, dict) else 0
        daily_limit = limits.get("max_searches_per_day", 0) if isinstance(limits, dict) else 0

        # Check if period_start is outdated (quota resets at 00:00 UTC)
        # If period_start is from a previous day, the counter should have reset
        period_start_info = None
        daily_used = daily_used_raw
        previous_period_used = None
        if isinstance(daily_usage, dict):
            period_start = daily_usage.get("period_start")
            if period_start:
                try:
                    from datetime import datetime, timezone

                    # Parse period_start date
                    period_date = datetime.strptime(period_start, "%Y-%m-%d").date()
                    current_date = datetime.now(timezone.utc).date()

                    # Check if period_start is from a previous day (in UTC)
                    # Note: Quota resets at 00:00 UTC regardless of user's timezone
                    days_diff = (current_date - period_date).days
                    if days_diff >= 1:
                        # If period_start is from yesterday or older (in UTC), the quota counter should have reset at 00:00 UTC
                        # The searches_used value from API is from the previous period, not the current one
                        # Store the previous period value for reference
                        previous_period_used = daily_used_raw
                        # Since quota resets at 00:00 UTC (regardless of user timezone), show 0 for the current period
                        # (unless there's been activity today in UTC, in which case the API would have updated period_start)
                        daily_used = 0  # Counter reset at 00:00 UTC
                        if days_diff > 1:
                            period_start_info = (
                                f"⚠️ period_start is {days_diff} days old ({period_start} UTC). "
                                f"Quota resets daily at 00:00 UTC (regardless of your timezone). "
                                f"Previous period ({period_start} UTC): {previous_period_used}/{daily_limit}. "
                                f"Current period ({current_date} UTC): {daily_used}/{daily_limit}."
                            )
                        else:
                            period_start_info = (
                                f"ℹ️ period_start is from yesterday ({period_start} UTC). "
                                f"Quota resets daily at 00:00 UTC (regardless of your timezone). "
                                f"Previous period ({period_start} UTC): {previous_period_used}/{daily_limit}. "
                                f"Current period ({current_date} UTC): {daily_used}/{daily_limit}."
                            )
                except (ValueError, TypeError):
                    # period_start format is not as expected, skip validation
                    pass

        # Calculate percentage
        percentage = None
        if daily_limit > 0:
            percentage = (daily_used / daily_limit) * 100

        # Determine status
        status = "ok"
        message = None
        if daily_limit > 0:
            if daily_used >= daily_limit:
                status = "exceeded"
                message = f"Quota exceeded: {daily_used}/{daily_limit} searches used"
            elif percentage and percentage >= 90:
                status = "warning"
                message = f"Quota almost exceeded: {daily_used}/{daily_limit} ({percentage:.1f}%)"
            elif percentage and percentage >= 75:
                status = "warning"
                message = f"Quota usage high: {daily_used}/{daily_limit} ({percentage:.1f}%)"
            else:
                message = f"Quota available: {daily_used}/{daily_limit} ({percentage:.1f}%)"

        # Prepend period_start info to message if available (more prominent)
        if period_start_info:
            if message:
                message = period_start_info + " " + message
            else:
                message = period_start_info

        return QuotaResponse(
            usage=usage if isinstance(usage, dict) else None,
            limits=limits if isinstance(limits, dict) else None,
            daily_used=daily_used,
            daily_limit=daily_limit,
            percentage=percentage,
            status=status,
            message=message,
        )

    except Exception as e:
        return QuotaResponse(
            usage=None,
            limits=None,
            daily_used=None,
            daily_limit=None,
            percentage=None,
            status="error",
            message=f"Error checking quota: {str(e)}",
        )


@app.get("/posts/count", response_model=PostsCountResponse)
async def count_posts_by_status_endpoint(
    status: str = "noreplies",
    candidate_id: str | None = None,
    platform: str | None = None,
    country: str | None = None,
    updated_today: bool = False,
):
    """
    Count posts with a specific status in Firestore.

    This endpoint allows querying the count of posts by status (noreplies, done, skipped)
    with optional filters. Useful for monitoring post states.

    Note: Posts do NOT have a 'pending' status. Valid post statuses are:
    - 'noreplies': Post pendiente de procesar (default)
    - 'done': Post procesado exitosamente
    - 'skipped': Post saltado porque max_replies <= 0

    Args:
        status: Post status to count. Default is 'noreplies'. Valid values: 'noreplies', 'done', 'skipped'
        candidate_id: Optional candidate_id to filter posts
        platform: Optional platform to filter posts (e.g., 'twitter', 'instagram')
        country: Optional country to filter posts
        updated_today: If True, only count posts updated today (default: False)

    Returns:
        PostsCountResponse with count, status, and applied filters.

    Raises:
        HTTPException: If the query fails or configuration is missing

    Examples:
        # Count posts pending to process (noreplies)
        GET /posts/count?status=noreplies

        # Count posts pending to process for a specific candidate
        GET /posts/count?status=noreplies&candidate_id=hnd09sosa

        # Count done posts
        GET /posts/count?status=done

        # Count skipped posts
        GET /posts/count?status=skipped

        # Count with multiple filters
        GET /posts/count?status=noreplies&candidate_id=hnd09sosa&platform=twitter&country=honduras

        # Count posts updated today
        GET /posts/count?status=done&updated_today=true
    """
    try:
        count = count_posts_by_status(
            status=status,
            candidate_id=candidate_id,
            platform=platform,
            country=country,
            updated_today=updated_today,
        )
        return PostsCountResponse(
            count=count,
            status=status,
            filters={
                "candidate_id": candidate_id,
                "platform": platform,
                "country": country,
                "updated_today": updated_today,
            },
        )
    except Exception as e:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error counting posts by status: {str(e)}",
        )


@app.post("/empty-result-jobs/retry", response_model=RetryEmptyResultJobsResponse)
async def retry_empty_result_jobs_endpoint(
    candidate_id: str | None = None,
    platform: str | None = None,
    country: str | None = None,
    limit: int | None = None,
):
    """
    Retry jobs with status='empty_result' by moving them to 'pending' status.

    This endpoint:
    1. Queries Firestore for jobs with status='empty_result' (with optional filters)
    2. Moves each job to 'pending' status
    3. Increments retry_count automatically
    4. Ensures logs will show these as retries when processed by /process-jobs

    When these jobs are processed by /process-jobs, the logs will include:
    - is_retry: true
    - retry_count: the number of retry attempts

    This is useful when you want to reprocess jobs that previously returned empty results,
    perhaps after Information Tracer has had more time to process them or after fixing
    configuration issues.

    Args:
        candidate_id: Optional candidate_id to filter jobs
        platform: Optional platform to filter jobs (e.g., 'twitter', 'instagram')
        country: Optional country to filter jobs
        limit: Maximum number of jobs to retry. If None, retries all matching jobs.

    Returns:
        RetryEmptyResultJobsResponse with:
        - total_found: Total number of empty_result jobs found
        - retried: Number of jobs successfully retried
        - errors: List of error messages (if any)
        - retried_jobs: List of jobs that were retried with their details

    Raises:
        HTTPException: If the processing fails or configuration is missing

    Example:
        # Retry all empty_result jobs
        POST /empty-result-jobs/retry

        # Retry with limit
        POST /empty-result-jobs/retry?limit=10

        # Retry for specific candidate
        POST /empty-result-jobs/retry?candidate_id=hnd09sosa

        # Retry with multiple filters
        POST /empty-result-jobs/retry?candidate_id=hnd09sosa&platform=twitter&limit=5
    """
    try:
        results = retry_empty_result_jobs_service(
            candidate_id=candidate_id,
            platform=platform,
            country=country,
            limit=limit,
        )
        return RetryEmptyResultJobsResponse(**results)
    except Exception as e:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrying empty result jobs: {str(e)}",
        )


@app.post("/json-to-parquet", response_model=JsonToParquetResponse)
async def json_to_parquet_endpoint(
    country: str | None = None,
    platform: str | None = None,
    candidate_id: str | None = None,
    skip_timestamp_filter: bool = False,
):
    """
    Convert JSON files from GCS raw layer to Parquet format with incremental loading.

    This endpoint:
    1. Reads JSON files from GCS raw layer (raw/{country}/{platform}/...)
    2. Flattens nested structures into tabular format
    3. Groups by ingestion_date and platform
    4. For each partition, reads existing Parquet if it exists and merges with new data
    5. Writes updated Parquet files to GCS processed layer

    OPTIMIZATIONS FOR EFFICIENCY:

    a) Timestamp-based filtering (incremental loading):
       - Uses MAX(ingestion_timestamp) from Parquet records (not blob.updated) for accurate filtering
       - blob.updated updates every time Parquet is written, but ingestion_timestamp reflects actual data timestamps
       - Only downloads and processes JSONs that are newer than the max ingestion_timestamp in Parquet
       - Lazy-loads max timestamps only when encountering JSONs for that partition (avoids reading all Parquet upfront)
       - Uses 1-hour buffer to handle edge cases where Parquet was just updated
       - Skips JSONs that are more than 1 hour older than Parquet max ingestion_timestamp
       - This avoids unnecessary network I/O and CPU processing while ensuring correct incremental behavior

    b) Incremental merging:
       - Reads existing Parquet files only when needed (when new JSONs exist for that partition)
       - Merges new records with existing ones in memory
       - Deduplicates by (source_file, tweet_id) to avoid duplicates

    c) Selective processing:
       - Only processes JSONs matching the specified filters (country/platform/candidate_id)
       - Uses GCS blob metadata (updated timestamp) without downloading content first
       - Downloads JSON content only for files that need processing

    This endpoint supports incremental loading - it will not overwrite existing Parquet files
    for the same date/platform combination. Instead, it will merge new records with existing ones,
    deduplicating by source_file and tweet_id.

    This endpoint should be called after /process-jobs or /fix-jobs endpoints that generate JSONs.

    Args:
        country: Country name to filter (e.g., 'honduras'). If None, processes all countries.
        platform: Platform name to filter (e.g., 'twitter', 'instagram'). If None, processes all platforms.
        candidate_id: Candidate ID to filter. If None, processes all candidates.
        skip_timestamp_filter: If True, processes all JSONs regardless of timestamp (relies on deduplication).
                              If False, uses timestamp-based optimization comparing JSON ingestion_ts with
                              MAX(ingestion_timestamp) from Parquet records to skip already-processed JSONs.
                              Use skip_timestamp_filter=true if new JSONs are not being processed due to timestamp issues.

    Returns:
        JsonToParquetResponse with processing results including records processed, files written, etc.

    Raises:
        HTTPException: If the processing fails or configuration is missing
    """
    import logging

    logger = logging.getLogger(__name__)
    print(
        f"[JSON-TO-PARQUET] Received request: country={country}, platform={platform}, "
        f"candidate_id={candidate_id}, skip_timestamp_filter={skip_timestamp_filter}"
    )
    logger.info(
        f"Received json-to-parquet request: country={country}, platform={platform}, "
        f"candidate_id={candidate_id}, skip_timestamp_filter={skip_timestamp_filter}"
    )
    try:
        results = json_to_parquet_service(
            country=country,
            platform=platform,
            candidate_id=candidate_id,
            skip_timestamp_filter=skip_timestamp_filter,
        )
        logger.info(
            f"json-to-parquet completed: processed={results.get('processed', 0)}, "
            f"succeeded={results.get('succeeded', 0)}, failed={results.get('failed', 0)}"
        )
        return JsonToParquetResponse(**results)
    except Exception as e:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error converting JSON to Parquet: {str(e)}",
        )
