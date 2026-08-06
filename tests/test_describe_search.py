"""Query normalization and the query-vector cache backing /search/describe."""
from __future__ import annotations

import pytest

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
