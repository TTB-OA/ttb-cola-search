"""Provider registry and configuration-driven selection."""
from __future__ import annotations

from collections.abc import Callable

from ..config import Settings, get_settings
from .base import Embedder
from .providers.gemini import GeminiEmbedder

EmbedderFactory = Callable[[Settings], Embedder]

_PROVIDERS: dict[str, EmbedderFactory] = {}


def register(name: str) -> Callable[[EmbedderFactory], EmbedderFactory]:
    def decorator(factory: EmbedderFactory) -> EmbedderFactory:
        _PROVIDERS[name] = factory
        return factory

    return decorator


@register("gemini")
def _make_gemini(settings: Settings) -> Embedder:
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    return GeminiEmbedder(
        model_id=settings.embedding_model,
        dim=settings.embedding_dim,
        api_key=settings.gemini_api_key,
    )


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        settings = get_settings()
        factory = _PROVIDERS.get(settings.embedding_provider)
        if factory is None:
            raise RuntimeError(
                f"Unknown embedding provider '{settings.embedding_provider}'. "
                f"Available: {sorted(_PROVIDERS)}"
            )
        _embedder = factory(settings)
    return _embedder


def available_providers() -> list[str]:
    return sorted(_PROVIDERS)
