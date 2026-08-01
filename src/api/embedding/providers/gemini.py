"""Google Gemini embedding provider (Gemini Developer API via GEMINI_API_KEY).

The blocking google-genai SDK calls are dispatched to a worker thread so they do
not block the event loop.
"""
from __future__ import annotations

import asyncio

from google import genai
from google.genai import types

from ..base import Embedder


class GeminiEmbedder(Embedder):
    provider_name = "gemini"

    def __init__(self, model_id: str, dim: int, api_key: str) -> None:
        self.model_id = model_id
        self.dim = dim
        self._client = genai.Client(api_key=api_key)

    def _embed_sync(self, contents: object) -> list[float]:
        response = self._client.models.embed_content(
            model=self.model_id,
            contents=contents,  # type: ignore[arg-type]
            config=types.EmbedContentConfig(output_dimensionality=self.dim),
        )
        embeddings = response.embeddings or []
        if not embeddings or not embeddings[0].values:
            raise RuntimeError("Gemini returned no embedding values")
        return list(embeddings[0].values)

    async def embed_text(self, text: str) -> list[float]:
        return await asyncio.to_thread(self._embed_sync, text)

    async def embed_image(self, data: bytes, mime_type: str = "image/jpeg") -> list[float]:
        part = types.Part.from_bytes(data=data, mime_type=mime_type)
        return await asyncio.to_thread(self._embed_sync, part)
