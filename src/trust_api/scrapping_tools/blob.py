"""Vercel Blob storage layer (replaces GCS) via the Blob REST API.

Details follow the @vercel/blob JS SDK (packages/blob/src in vercel/storage):
- PUT  /?pathname=<path>          upload (body = raw bytes)
- GET  /?url=<path>               head/metadata (404 => does not exist)
- GET  /?prefix=&cursor=&limit=   list (paginated via cursor/hasMore)
- PUT  /?pathname=<to>&fromUrl=   copy
- POST /delete                    delete {"urls": [...]}

Reads download via the public delivery URL resolved from head/list.
"""

import logging
from dataclasses import dataclass
from datetime import datetime

import httpx

from trust_api.scrapping_tools.core.config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://blob.vercel-storage.com"
API_VERSION = "13"  # BLOB_API_VERSION in @vercel/blob


@dataclass
class BlobInfo:
    pathname: str
    url: str
    size: int
    uploaded_at: datetime | None


def _token() -> str:
    token = settings.blob_read_write_token
    if not token:
        raise ValueError("BLOB_READ_WRITE_TOKEN is not configured")
    return token


def _headers() -> dict[str, str]:
    token = _token()
    headers = {
        "authorization": f"Bearer {token}",
        "x-api-version": API_VERSION,
    }
    # Store id is embedded in read-write tokens: vercel_blob_rw_{storeId}_{secret}
    parts = token.split("_")
    if len(parts) >= 5 and parts[0] == "vercel" and parts[1] == "blob":
        headers["x-vercel-blob-store-id"] = parts[3]
    return headers


def _request(method: str, url: str, **kwargs) -> httpx.Response:
    headers = {**_headers(), **kwargs.pop("headers", {})}
    response = httpx.request(method, url, headers=headers, timeout=60.0, **kwargs)
    return response


def uri(path: str) -> str:
    """Scheme URI used in logs/responses where 'gs://bucket/path' used to appear."""
    return f"blob://{path}"


def put(path: str, data: bytes | str, content_type: str) -> str:
    """Upload data to the store at the given pathname. Returns the public URL."""
    body = data.encode("utf-8") if isinstance(data, str) else data
    response = _request(
        "PUT",
        BASE_URL + "/",
        params={"pathname": path},
        content=body,
        headers={
            "x-content-type": content_type,
            "x-add-random-suffix": "0",
            "x-allow-overwrite": "1",
            "x-vercel-blob-access": "public",
        },
    )
    response.raise_for_status()
    return response.json()["url"]


def _head(path: str) -> dict | None:
    response = _request("GET", BASE_URL + "/", params={"url": path})
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def exists(path: str) -> bool:
    return _head(path) is not None


def _url_for(path: str) -> str | None:
    meta = _head(path)
    if meta is None:
        return None
    return meta.get("url")


def get_bytes(path: str) -> bytes | None:
    url = _url_for(path)
    if url is None:
        return None
    response = httpx.get(url, timeout=60.0)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.content


def get_text(path: str) -> str | None:
    data = get_bytes(path)
    if data is None:
        return None
    return data.decode("utf-8")


def list_blobs(prefix: str) -> list[BlobInfo]:
    """List all blobs under a prefix, following cursor pagination."""
    blobs: list[BlobInfo] = []
    cursor: str | None = None
    while True:
        params: dict[str, str] = {"prefix": prefix, "limit": "1000"}
        if cursor:
            params["cursor"] = cursor
        response = _request("GET", BASE_URL + "/", params=params)
        response.raise_for_status()
        data = response.json()
        for item in data.get("blobs", []):
            uploaded_at = item.get("uploadedAt")
            blobs.append(
                BlobInfo(
                    pathname=item["pathname"],
                    url=item["url"],
                    size=item.get("size", 0),
                    uploaded_at=(
                        datetime.fromisoformat(uploaded_at.replace("Z", "+00:00"))
                        if uploaded_at
                        else None
                    ),
                )
            )
        if not data.get("hasMore"):
            break
        cursor = data.get("cursor")
        if not cursor:
            break
    return blobs


def copy(src_path: str, dst_path: str) -> str:
    """Copy a blob within the store. Returns the destination public URL."""
    response = _request(
        "PUT",
        BASE_URL + "/",
        params={"pathname": dst_path, "fromUrl": src_path},
        headers={
            "x-add-random-suffix": "0",
            "x-allow-overwrite": "1",
            "x-vercel-blob-access": "public",
        },
    )
    response.raise_for_status()
    return response.json()["url"]


def delete(path: str) -> None:
    response = _request(
        "POST",
        BASE_URL + "/delete",
        json={"urls": [path]},
    )
    response.raise_for_status()
