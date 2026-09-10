"""Google Gemini embedding provider (Gemini Developer API via GEMINI_API_KEY).

The blocking google-genai SDK calls are dispatched to a worker thread so they do
not block the event loop.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

from google import genai
from google.genai import errors, types

from ..base import Embedder, EmbeddingRateLimited

# The SDK retries transient statuses on its own, but its default ceiling (120s)
# is far longer than a search request should ever wait. Keeping the budget to a
# couple of seconds absorbs a brief quota blip while letting a sustained one
# fail fast enough to tell the user to retry.
_RETRY = types.HttpRetryOptions(
    attempts=3,
    initial_delay=0.5,
    max_delay=4.0,
    http_status_codes=[408, 429, 500, 502, 503, 504],
)

_RETRY_AFTER_FALLBACK_SECONDS = 15.0


def _retry_after_seconds(exc: errors.APIError) -> float:
    """Best-effort read of the provider's own backoff hint."""
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers is not None:
        raw = headers.get("Retry-After") or headers.get("retry-after")
        if raw:
            try:
                return float(raw)
            except (TypeError, ValueError):
                pass

    # Google's RetryInfo rider, e.g. {"@type": ".../RetryInfo", "retryDelay": "27s"}.
    details: Any = getattr(exc, "details", None)
    if isinstance(details, dict):
        for item in details.get("error", {}).get("details") or []:
            delay = item.get("retryDelay") if isinstance(item, dict) else None
            if isinstance(delay, str) and (m := re.fullmatch(r"(\d+(?:\.\d+)?)s", delay)):
                return float(m.group(1))

    return _RETRY_AFTER_FALLBACK_SECONDS


class GeminiEmbedder(Embedder):
    provider_name = "gemini"

    def __init__(self, model_id: str, dim: int, api_key: str) -> None:
        self.model_id = model_id
        self.dim = dim
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(retry_options=_RETRY),
        )

    def _embed_sync(self, contents: object) -> list[float]:
        try:
            response = self._client.models.embed_content(
                model=self.model_id,
                contents=contents,  # type: ignore[arg-type]
                config=types.EmbedContentConfig(output_dimensionality=self.dim),
            )
        except errors.APIError as exc:
            if getattr(exc, "code", None) == 429:
                raise EmbeddingRateLimited(_retry_after_seconds(exc)) from exc
            raise
        embeddings = response.embeddings or []
        if not embeddings or not embeddings[0].values:
            raise RuntimeError("Gemini returned no embedding values")
        return list(embeddings[0].values)

    async def embed_text(self, text: str) -> list[float]:
        return await asyncio.to_thread(self._embed_sync, text)

    async def embed_image(self, data: bytes, mime_type: str = "image/jpeg") -> list[float]:
        part = types.Part.from_bytes(data=data, mime_type=mime_type)
        return await asyncio.to_thread(self._embed_sync, part)
