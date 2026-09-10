"""Embedder interface shared by all providers."""
from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingRateLimited(Exception):
    """The provider refused the call because its quota is exhausted.

    Distinct from a provider outage: the caller should back off and retry rather
    than be told the feature is unavailable.
    """

    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("Embedding provider rate limit reached")
        self.retry_after = retry_after


class Embedder(ABC):
    """Turns images and text into fixed-length vectors.

    Implementations set ``provider_name``, ``model_id`` and ``dim``. The vector
    dimension MUST match the pgvector column dimension used for storage.
    """

    provider_name: str = "base"
    model_id: str = ""
    dim: int = 0

    @abstractmethod
    async def embed_image(self, data: bytes, mime_type: str = "image/jpeg") -> list[float]:
        """Return an embedding for the given image bytes."""

    @abstractmethod
    async def embed_text(self, text: str) -> list[float]:
        """Return an embedding for the given text."""

    async def health(self) -> bool:
        try:
            await self.embed_text("healthcheck")
            return True
        except Exception:  # noqa: BLE001 - probe should degrade to False, never bubble
            return False
