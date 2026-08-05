"""In-process rate limiting for endpoints that cost money or CPU per call.

State is per replica, so the effective ceiling scales with replica count. This
is here to stop a single client looping on the paid embedding call, not to
enforce a precise global quota — that would need shared state.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Any


class SlidingWindowLimiter:
    """Allows `limit` events per `window_seconds` for each key."""

    def __init__(self, limit: int, window_seconds: float, max_keys: int = 4096) -> None:
        self._limit = limit
        self._window = float(window_seconds)
        self._max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}

    def _evict(self, now: float) -> None:
        # Bound the table itself, or tracking becomes its own memory exhaustion.
        for key in [k for k, v in self._hits.items() if not v or now - v[-1] > self._window]:
            del self._hits[key]
        while len(self._hits) >= self._max_keys:
            del self._hits[min(self._hits, key=lambda k: self._hits[k][-1])]

    def check(self, key: str) -> float | None:
        """Record a hit and return None, or the seconds to wait if over limit."""
        now = time.monotonic()
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= self._max_keys:
                self._evict(now)
            hits = self._hits.setdefault(key, deque())

        cutoff = now - self._window
        while hits and hits[0] <= cutoff:
            hits.popleft()

        if len(hits) >= self._limit:
            return max(0.0, self._window - (now - hits[0]))

        hits.append(now)
        return None


def client_key(request: Any, trust_forwarded_for: bool) -> str:
    """Identify the caller, preferring the proxy-supplied client address.

    X-Forwarded-For is only consulted when the API is known to sit behind a
    trusted reverse proxy, since clients can otherwise spoof it to reset their
    own bucket.
    """
    headers = getattr(request, "headers", {}) or {}
    if trust_forwarded_for:
        forwarded = headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    client = getattr(request, "client", None)
    host = getattr(client, "host", None) if client else None
    return host or "unknown"
