"""Sliding-window limiter behaviour and client identification."""
from __future__ import annotations

import time

import pytest

from src.api.ratelimit import SlidingWindowLimiter, client_key


class FakeRequest:
    def __init__(self, headers=None, host="10.0.0.1"):
        self.headers = headers or {}
        self.client = type("C", (), {"host": host})() if host else None


def test_allows_up_to_the_limit_then_blocks():
    limiter = SlidingWindowLimiter(limit=3, window_seconds=60)
    assert [limiter.check("a") for _ in range(3)] == [None, None, None]

    retry_after = limiter.check("a")
    assert retry_after is not None
    assert 0 < retry_after <= 60


def test_keys_are_independent():
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
    assert limiter.check("a") is None
    assert limiter.check("b") is None
    assert limiter.check("a") is not None


def test_window_expiry_frees_the_slot():
    limiter = SlidingWindowLimiter(limit=1, window_seconds=0.05)
    assert limiter.check("a") is None
    assert limiter.check("a") is not None
    time.sleep(0.06)
    assert limiter.check("a") is None


def test_key_table_stays_bounded():
    limiter = SlidingWindowLimiter(limit=5, window_seconds=60, max_keys=32)
    for i in range(500):
        limiter.check(f"key-{i}")
    assert len(limiter._hits) <= 32


def test_forwarded_header_used_only_when_trusted():
    request = FakeRequest({"x-forwarded-for": "203.0.113.7, 70.41.3.18"})
    assert client_key(request, trust_forwarded_for=True) == "203.0.113.7"
    assert client_key(request, trust_forwarded_for=False) == "10.0.0.1"


@pytest.mark.parametrize("headers", [{}, {"x-forwarded-for": "   "}])
def test_falls_back_to_peer_address(headers):
    assert client_key(FakeRequest(headers), trust_forwarded_for=True) == "10.0.0.1"


def test_unknown_client_is_handled():
    assert client_key(FakeRequest(host=None), trust_forwarded_for=True) == "unknown"
