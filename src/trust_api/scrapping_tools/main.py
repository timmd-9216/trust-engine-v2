import httpx
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

from trust_api.scrapping_tools.core.config import settings
from trust_api.scrapping_tools.services import fetch_post_information, process_posts_service


class PostInformationRequest(BaseModel):
    post_id: str


class PostInformationResponse(BaseModel):
    post_id: str
    data: dict


class ProcessPostsResponse(BaseModel):
    processed: int
    succeeded: int
    failed: int
    errors: list[str]
    saved_files: list[str]
    log_file: str | None = None  # GCS URI of the execution log file


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
        data = fetch_post_information(request.post_id)
        return PostInformationResponse(post_id=request.post_id, data=data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Configuration error: {str(e)}",
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"External service error: {str(e)}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching post information: {str(e)}",
        )


@app.post("/process-posts", response_model=ProcessPostsResponse)
async def process_posts_endpoint(max_posts: int | None = None):
    """
    Process posts from Firestore that have status='noreplies'.

    This endpoint:
    1. Queries Firestore collection 'posts' for documents with status='noreplies'
    2. For each post, queries the external Information Tracer service using post_id
    3. Saves the JSON response to GCS bucket with structure:
       country/platform/candidate_id/{post_id}.json
    4. Updates the post status to 'done' in Firestore after successful save

    Args:
        max_posts: Maximum number of posts to process in this call. If None, processes all posts with status='noreplies'.

    Returns:
        ProcessPostsResponse with processing results including success count, errors, etc.

    Raises:
        HTTPException: If the processing fails or configuration is missing
    """
    try:
        results = process_posts_service(max_posts=max_posts)
        return ProcessPostsResponse(**results)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing posts: {str(e)}",
        )
