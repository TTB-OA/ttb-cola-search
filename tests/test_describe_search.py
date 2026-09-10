"""Query normalization and the query-vector cache backing /search/describe."""
from __future__ import annotations

import pytest

from src.api.embedding import EmbeddingRateLimited
from src.api.embedding.providers import gemini
from src.api.routers import search


@pytest.fixture(autouse=True)
def clear_cache():
    search._query_vector_cache.clear()
    yield
    search._query_vector_cache.clear()


def test_normalize_folds_case_and_collapses_whitespace():
    assert search.normalize_query("  A  Dark\tGreen   Bottle\n") == "a dark green bottle"


def test_normalize_is_stable_across_equivalent_phrasings():
    variants = ["gold eagle crest", "Gold Eagle Crest", "gold  eagle   crest "]
    assert len({search.normalize_query(v) for v in variants}) == 1


def test_cache_returns_stored_literal():
    search.store_query_vector("red label", "[0.1,0.2]")
    assert search.cached_query_vector("red label") == "[0.1,0.2]"


def test_cache_misses_are_none():
    assert search.cached_query_vector("never stored") is None


def test_cache_evicts_least_recently_used_at_the_cap():
    cap = search._QUERY_VECTOR_CACHE_SIZE
    for i in range(cap):
        search.store_query_vector(f"q{i}", f"[{i}]")

    # Touch the oldest so it is no longer the eviction candidate.
    assert search.cached_query_vector("q0") == "[0]"
    search.store_query_vector("overflow", "[999]")

    assert len(search._query_vector_cache) == cap
    assert search.cached_query_vector("q0") == "[0]"
    assert search.cached_query_vector("q1") is None
    assert search.cached_query_vector("overflow") == "[999]"


def test_provider_rate_limit_is_a_429_with_retry_after():
    exc = search._provider_busy(EmbeddingRateLimited(retry_after=2.4))
    assert exc.status_code == 429
    assert exc.headers["Retry-After"] == "3"
    assert "try again" in exc.detail


def test_provider_rate_limit_without_a_hint_still_sets_retry_after():
    exc = search._provider_busy(EmbeddingRateLimited())
    assert exc.status_code == 429
    assert int(exc.headers["Retry-After"]) >= 1


class _FakeApiError(Exception):
    def __init__(self, headers=None, details=None):
        super().__init__("rate limited")
        self.code = 429
        self.response = type("R", (), {"headers": headers})() if headers is not None else None
        self.details = details


def test_retry_after_prefers_the_response_header():
    exc = _FakeApiError(headers={"Retry-After": "8"})
    assert gemini._retry_after_seconds(exc) == 8.0


def test_retry_after_falls_back_to_google_retry_info():
    exc = _FakeApiError(details={"error": {"details": [{"retryDelay": "27s"}]}})
    assert gemini._retry_after_seconds(exc) == 27.0


def test_retry_after_defaults_when_the_provider_gives_no_hint():
    assert gemini._retry_after_seconds(_FakeApiError()) == gemini._RETRY_AFTER_FALLBACK_SECONDS
