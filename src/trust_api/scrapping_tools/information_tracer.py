import logging
import os
import time
from typing import Literal

import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

HOST = "https://informationtracer.com"
SUBMIT_URL = f"{HOST}/submit"
STATUS_URL = f"{HOST}/status"
RAWDATA_URL = f"{HOST}/rawdata"

API_KEY = os.getenv("INFORMATION_TRACER_API_KEY", "")

PlatformType = Literal[
    "twitter",
    "facebook",
    "instagram",
    "reddit",
    "youtube",
    # "weibo",
    "threads",
    # "bluesky",
]


def check_api_usage(token: str | None = None) -> dict:
    """Check API usage statistics for the Information Tracer account.

    Args:
        token: API token for authentication. If None, uses the API_KEY from environment variables.

    Returns:
        Dictionary containing account statistics and usage information.
    """
    if token is None:
        token = API_KEY
    url = f"{HOST}/account_stat?token={token}"
    response = requests.get(url)
    return response.json()


def submit(
    token: str,
    query: str,
    max_post: int,
    sort_by: Literal["time", "engagement"],
    start_date: str,
    end_date: str,
    platform: PlatformType | list[PlatformType],
    timeline_only: bool,
    enable_ai: bool,
) -> tuple[str | None, dict]:
    """Submit a data collection job to Information Tracer API.

    This function submits a request to collect social media posts from various platforms.
    For account searches, data is collected in reverse chronological order, and start_date is ignored.
    The end_date parameter specifies the earliest date to collect posts from.

    Args:
        token: API authentication token.
        query: Search query. Format depends on search type:
            - Account search: username (e.g., 'whitehouse')
            - Keyword search: 'from:@username' (e.g., 'from:@whitehouse')
            - Reply search: 'reply:post_id' (e.g., 'reply:2000043080984998363')
        max_post: Maximum number of posts to collect. Platform limits:
            - Twitter: 10000
            - Facebook: 100
            - Instagram: 100
            - Reddit: 500
            - YouTube: 500
            - Weibo: 200
            - Threads: 200
            - Bluesky: 500
        sort_by: Sort order ('time' or 'engagement'). Only applies to keyword search.
        start_date: Start date in 'YYYY-MM-DD' format (ignored for account search).
        end_date: End date in 'YYYY-MM-DD' format (earliest date to collect from).
        platform: Single platform or list of platforms to collect from.
        timeline_only: If True, uses account search (includes retweets).
                      If False, uses keyword search (excludes retweets).
        enable_ai: Enable AI features for the collection.

    Returns:
        A tuple containing:
            - The job ID (id_hash256) if submission is successful, None otherwise
            - Dictionary with the request parameters used

    Examples:
        Collect posts from Twitter account (including retweets):
            >>> submit(token, 'whitehouse', 100, 'time', '2025-01-01', '2025-12-01', 'twitter', True, False)

        Collect posts from Twitter account (excluding retweets):
            >>> submit(token, 'from:@whitehouse', 100, 'time', '2025-01-01', '2025-12-01', 'twitter', False, False)

        Collect replies from Twitter post:
            >>> submit(token, 'reply:2000043080984998363', 100, 'time', '2025-01-01', '2025-12-01', 'twitter', False, False)
    """
    # for account search, we always get data in reverse chronologicall order.
    # for account search, start_date is IRNORED
    # start_date = '2020-01-01'

    # for account search, end_date means we want to collect posts until...
    # for example, if today is 2025-04-01, and end_date is 2025-03-28,
    # then we collect posts on 2025-04-01, 2025-03-31, 2025-03-30, 2025-03-29, 2025-03-28
    # end_date = '2025-12-01'

    # maximum number of post, currently the maximum allowed value is for each platform is
    # tweet: 10000
    # facebook: 100
    # instagram: 100
    # reddit: 500
    # youtube: 500
    # weibo: 200
    # threads: 200
    # bluesky: 500
    # max_post = 20

    # sort_by = 'time' # time or engagement, only applies to keyword search

    ##### EXAMPLES
    ########## collect posts from X account whitehouse (account search approach, including retweets)
    # query must be a valid X screen_name
    # query = 'whitehouse'
    # platform = 'twitter'
    # timeline_only = True

    ########## collect posts from X account whitehouse (keyword search approach, excluding retweets)
    # query must be a valid X screen_name
    # query = 'from:@whitehouse'
    # platform = 'twitter'
    # timeline_only = False

    ########## collect replies from X post id 2000043080984998363
    # query = 'reply:2000043080984998363'
    # platform = 'twitter'
    # timeline_only = False

    ########## collect posts from instagram account whitehouse
    # query = 'whitehouse'
    # platform = 'instagram'
    # timeline_only = True

    ########## collect replies from instagram post with pk value 3779633486450567735
    # query = 'reply:3779633486450567735'
    # platform = 'instagram'
    # timeline_only = False

    ########## collect posts from Facebook account whitehouse
    # query = 'whitehouse'
    # platform = 'facebook'
    # timeline_only = True

    id_hash256 = None

    requests_params = {
        "query": query,
        "platform": platform,
        "timeline_only": timeline_only,
        "enable_ai": enable_ai,
        "start_date": start_date,
        "end_date": end_date,
        "max_post": max_post,
        "sort_by": sort_by,
    }

    try:
        response = requests.post(
            SUBMIT_URL,
            timeout=25,
            json={
                "query": query,
                "token": token,
                "max_post": max_post,
                "sort_by": sort_by,
                "start_date": start_date,
                "end_date": end_date,
                "platform_to_collect": [platform],
                "timeline_only": timeline_only,
                "enable_ai": enable_ai,
            },
        )
        if "id_hash256" in response.json():
            id_hash256 = response.json()["id_hash256"]
        else:
            logger.error("Submission failed!")
            logger.error(response.json())

    except Exception as e:
        logger.error("Fatal Exception on server side!")
        logger.error("Submission failed!")
        logger.exception(e)

    return id_hash256, requests_params


def check_status(id_hash256: str, token: str) -> str:
    """Check the status of a submitted data collection job.

    Polls the Information Tracer API to monitor job progress. The function will check
    the status every 6 seconds for up to 80 rounds (8 minutes total).

    Args:
        id_hash256: The job ID returned from the submit() function.
        token: API authentication token.

    Returns:
        Status string indicating the job outcome:
            - 'finished': Job completed successfully
            - 'failed': Job failed (status not in response)
            - 'timeout': Job did not complete within maximum polling rounds
    """
    task_status = None
    MAX_ROUND = 80
    SLEEP_INTERVAL = 40
    current_round = 0
    include_partial_results = 0

    while task_status != "finished" and current_round < MAX_ROUND:
        current_round += 1
        logger.info(f"Checking status, round {current_round}")
        try:
            full_url = f"{STATUS_URL}?id_hash256={id_hash256}&token={token}&include_partial_results={include_partial_results}"

            response = requests.get(full_url, timeout=10).json()
            response.pop("tweet_preview", None)
            logger.debug(f"Status response: {response}")
            if "status" in response:
                task_status = response["status"]

                if task_status != "finished":
                    time.sleep(SLEEP_INTERVAL)
                else:
                    return "finished"
            else:
                logger.error("status is not in response")
                logger.error(f"Response: {response}")
                return "failed"
        except Exception as e:
            logger.error("Exception when checking job status!")
            logger.exception(e)
    return "timeout"


def get_result(
    id_hash256: str,
    token: str,
    platform: PlatformType,
) -> dict | list | None:
    """Retrieve and save the results of a completed data collection job.

    Fetches the collected data from the Information Tracer API and saves it as a JSON file.
    The output file contains both the collected data and the request parameters used.

    Args:
        id_hash256: The job ID returned from the submit() function.
        token: API authentication token.
        platform: The platform from which data was collected.

    Returns:
        dict | list: The collected data as a dictionary or list.
                     Returns a list (often empty []) when no results are found.
                     Returns None if there's an error.

    Raises:
        Logs errors if the request fails or file cannot be saved.
    """
    url = f"{RAWDATA_URL}?token={token}&id={id_hash256}&source={platform}"
    try:
        response = requests.get(url)
        records = response.json()
        # Information Tracer returns a list when there are results (or empty list if none)
        if isinstance(records, list):
            logger.info(f"Received {len(records)} records from {platform}")
        else:
            logger.info(f"Received result from {platform} (type: {type(records).__name__})")
        return records

    except Exception as e:
        logger.error("exception in requesting raw data")
        logger.exception(e)
        return None


def get_post_replies(
    post_id: str,
    platform: PlatformType,
    max_post: int = 100,
    token: str | None = None,
    sort_by: Literal["time", "engagement"] = "time",
) -> dict:
    """Get replies for a specific post using Information Tracer API.

    This function handles the complete workflow:
    1. Submits a job to collect replies for the given post_id
    2. Polls for job completion
    3. Retrieves and returns the collected replies

    Args:
        post_id: The ID of the post to get replies for.
        platform: The platform where the post is located (twitter, facebook, instagram, etc.).
        max_post: Maximum number of replies to collect. Default is 100.
                  Platform limits apply:
                  - Twitter: 10000
                  - Facebook: 100
                  - Instagram: 100
                  - Reddit: 500
                  - YouTube: 500
                  - Threads: 200
        token: API authentication token. If None, uses API_KEY from environment variables.
        sort_by: Sort order for replies ('time' or 'engagement'). Default is 'time'.
                 Note: Only applies to keyword search, not account search.

    Returns:
        dict: Dictionary containing:
            - "data": The collected replies (structure depends on the platform)
            - "job_id": The Information Tracer job ID (id_hash256)

    Raises:
        ValueError: If submission fails or job ID is not returned.
        RuntimeError: If job status check fails or times out.
        Exception: If result retrieval fails.

    Example:
        >>> result = get_post_replies("1234567890", "twitter", max_post=500)
        >>> print(f"Job ID: {result['job_id']}, Retrieved {len(result['data'])} replies")
    """
    if token is None:
        token = API_KEY

    if not token:
        raise ValueError(
            "API token is required. Set INFORMATION_TRACER_API_KEY environment variable or pass token parameter."
        )

    # Construct query for reply search: 'reply:post_id'
    query = f"reply:{post_id}"

    # Default parameters for reply collection
    # timeline_only must be False for reply searches
    timeline_only = False
    enable_ai = False
    # sort_by is passed as parameter (default: "time")
    start_date = "2020-01-01"  # Default start date (may be ignored for reply searches)
    end_date = "2025-12-31"  # Default end date

    logger.info(
        f"Submitting reply collection job for post_id={post_id}, platform={platform}, max_post={max_post}"
    )

    # Submit the job
    id_hash256, requests_params = submit(
        token=token,
        query=query,
        max_post=max_post,
        sort_by=sort_by,
        start_date=start_date,
        end_date=end_date,
        platform=platform,
        timeline_only=timeline_only,
        enable_ai=enable_ai,
    )

    if not id_hash256:
        error_msg = f"Failed to submit reply collection job for post_id={post_id}"
        logger.error(error_msg)
        raise ValueError(error_msg)

    logger.info(f"Job submitted successfully. Job ID: {id_hash256}")

    # Check job status and wait for completion
    status = check_status(id_hash256, token)

    if status != "finished":
        error_msg = f"Job did not complete successfully. Status: {status}, post_id={post_id}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    logger.info(f"Job completed successfully. Retrieving results for post_id={post_id}")

    # Get the results
    result = get_result(id_hash256, token, platform)

    if result is None:
        error_msg = f"Failed to retrieve results for post_id={post_id}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    if isinstance(result, list):
        logger.info(
            f"Successfully retrieved {len(result)} replies for post_id={post_id}, job_id={id_hash256}"
        )
    else:
        logger.info(f"Successfully retrieved results for post_id={post_id}, job_id={id_hash256}")

    return {"data": result, "job_id": id_hash256}


if __name__ == "__main__":
    # query = 'from:@whitehouse'
    query = "susanabejarano__"
    platform = "instagram"
    timeline_only = True

    enable_ai = False

    start_date = "2025-12-01"
    end_date = "2025-12-17"
    max_post = 2
    sort_by = "engagement"

    result = submit(
        API_KEY,
        query,
        max_post,
        sort_by,
        start_date,
        end_date,
        platform,
        timeline_only,
        enable_ai,
    )

    print(result)
