"""Azure Blob Storage access for private label images.

Uses a managed identity / DefaultAzureCredential to stream blob bytes through
the API so images are never publicly exposed.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import BlobServiceClient

from .config import get_settings

_service: BlobServiceClient | None = None
_credential: DefaultAzureCredential | None = None


def _get_service() -> BlobServiceClient:
    global _service, _credential
    settings = get_settings()
    if not settings.blob_account_url:
        raise RuntimeError("BLOB_ACCOUNT_URL is not configured")
    if _service is None:
        _credential = DefaultAzureCredential()
        _service = BlobServiceClient(
            account_url=settings.blob_account_url, credential=_credential
        )
    return _service


def _blob_client(blob_name: str):
    settings = get_settings()
    if not settings.blob_container:
        raise RuntimeError("BLOB_CONTAINER is not configured")
    return _get_service().get_blob_client(
        container=settings.blob_container, blob=blob_name
    )


class RangeNotSatisfiable(Exception):
    """A well-formed byte range that falls outside the blob."""

    def __init__(self, size: int) -> None:
        super().__init__(f"range outside blob of {size} bytes")
        self.size = size


async def stream_blob(blob_name: str) -> tuple[AsyncIterator[bytes], str]:
    """Return an async byte iterator and content type for ``blob_name``."""
    downloader = await _blob_client(blob_name).download_blob()
    content_type = (
        downloader.properties.content_settings.content_type or "application/octet-stream"
    )
    return downloader.chunks(), content_type


async def read_blob(blob_name: str) -> bytes:
    """Read ``blob_name`` fully into memory, for callers that cannot stream."""
    downloader = await _blob_client(blob_name).download_blob()
    return await downloader.readall()


def _parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Resolve a single-range ``bytes=`` header against a known blob size.

    Returns None when there is no usable range and the whole blob should be
    sent, and raises RangeNotSatisfiable when the range is well-formed but falls
    outside the blob, which is a 416 rather than a 200.
    """
    if not header:
        return None
    unit, _, spec = header.partition("=")
    # Multi-range requests are legal but no PMTiles client issues them, so the
    # whole blob is sent rather than building a multipart response.
    if unit.strip().lower() != "bytes" or "," in spec:
        return None

    start_txt, sep, end_txt = spec.strip().partition("-")
    if not sep:
        return None

    try:
        start = int(start_txt) if start_txt else None
        end = int(end_txt) if end_txt else None
    except ValueError:
        return None

    if start is None:
        # "-N": the final N bytes.
        if end is None or end <= 0:
            raise RangeNotSatisfiable(size)
        return max(0, size - end), size - 1

    end = size - 1 if end is None else min(end, size - 1)
    if start > end or start >= size:
        raise RangeNotSatisfiable(size)
    return start, end


async def stream_blob_range(
    blob_name: str, range_header: str | None
) -> tuple[AsyncIterator[bytes], int, str | None, int]:
    """Return chunks, length, Content-Range and total size for a ranged read.

    Content-Range is None when the whole blob is being returned, which is what
    tells the caller to answer 200 rather than 206.
    """
    client = _blob_client(blob_name)
    size = (await client.get_blob_properties()).size
    span = _parse_range(range_header, size)

    if span is None:
        downloader = await client.download_blob()
        return downloader.chunks(), size, None, size

    start, end = span
    length = end - start + 1
    downloader = await client.download_blob(offset=start, length=length)
    return downloader.chunks(), length, f"bytes {start}-{end}/{size}", size


async def close_blob() -> None:
    global _service, _credential
    if _service is not None:
        await _service.close()
        _service = None
    if _credential is not None:
        await _credential.close()
        _credential = None
