"""Azure Blob Storage access for private label images.

Uses a managed identity / DefaultAzureCredential to stream blob bytes through
the API so images are never publicly exposed.
"""
from __future__ import annotations

from typing import AsyncIterator

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


async def stream_blob(blob_name: str) -> tuple[AsyncIterator[bytes], str]:
    """Return an async byte iterator and content type for ``blob_name``."""
    settings = get_settings()
    if not settings.blob_container:
        raise RuntimeError("BLOB_CONTAINER is not configured")
    blob_client = _get_service().get_blob_client(
        container=settings.blob_container, blob=blob_name
    )
    downloader = await blob_client.download_blob()
    content_type = (
        downloader.properties.content_settings.content_type or "application/octet-stream"
    )
    return downloader.chunks(), content_type


async def close_blob() -> None:
    global _service, _credential
    if _service is not None:
        await _service.close()
        _service = None
    if _credential is not None:
        await _credential.close()
        _credential = None
