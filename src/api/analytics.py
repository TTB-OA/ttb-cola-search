"""Usage analytics event shaping.

Everything here is pure and synchronous so it can be unit tested without a
server, a database, or an exporter. The only side-effecting function is
:func:`emit`, which writes a structured log record that Azure Monitor picks up.

Collection policy: record *which* filters a user reached for, never *what* they
typed. Free-text values are reduced to length and term count unless
``analytics_capture_query_text`` is explicitly enabled.
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Mapping
from typing import Any

from .config import API_PREFIX
from .ratelimit import client_key

logger = logging.getLogger("analytics")
# These are structured events rather than diagnostics, so they must not be
# silenced by whatever level the rest of the application happens to run at.
logger.setLevel(logging.INFO)

# Router-local route template -> event name. FastAPI stores the path without the
# include prefix, so keys are unprefixed and route_key() normalises either form.
# Anything not listed is not a product event; it still shows up in request
# telemetry, it just carries no shaped attributes.
EVENT_BY_ROUTE: dict[tuple[str, str], str] = {
    ("GET", "/colas"): "search_performed",
    ("GET", "/colas/{cola_id}"): "detail_viewed",
    ("GET", "/colas/{cola_id}/similar"): "similar_requested",
    ("POST", "/search/image"): "image_search_performed",
}


def route_key(method: str, path: str) -> tuple[str, str]:
    return method, path.removeprefix(API_PREFIX)

# Query params that represent a user-applied filter. Names are recorded, values
# are not (except for the low-cardinality enums in FILTER_VALUE_KEYS).
FILTER_KEYS = (
    "q",
    "ttbId",
    "brand",
    "fanciful",
    "applicant",
    "business",
    "permit",
    "permitName",
    "permitState",
    "permitCity",
    "submitter",
    "varietal",
    "qualification",
    "labelText",
    "commodity",
    "source",
    "origin",
    "status",
    "dateFrom",
    "dateTo",
)

# Closed vocabularies, safe to record verbatim.
FILTER_VALUE_KEYS = ("commodity", "source", "origin", "status")

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

_SIZE_BUCKETS = ((256_000, "<250KB"), (1_000_000, "<1MB"), (4_000_000, "<4MB"))


def hash_identifier(value: str, salt: str) -> str:
    """Salted, truncated digest. Client addresses are PII and never stored raw."""
    return hashlib.sha256(f"{salt}|{value}".encode()).hexdigest()[:32]


def session_id_from(request: Any, *, trust_forwarded_for: bool, salt: str) -> str:
    """Pseudonymous session id: the client-supplied one, else a hashed address."""
    headers = getattr(request, "headers", {}) or {}
    supplied = (headers.get("x-client-session") or "").strip().lower()
    if _UUID_RE.match(supplied):
        return supplied
    return hash_identifier(client_key(request, trust_forwarded_for), salt)


def size_bucket(num_bytes: int | None) -> str:
    if num_bytes is None or num_bytes < 0:
        return "unknown"
    for ceiling, label in _SIZE_BUCKETS:
        if num_bytes < ceiling:
            return label
    return ">=4MB"


def _int(params: Mapping[str, str], key: str, default: int) -> int:
    try:
        return int(params[key])
    except (KeyError, TypeError, ValueError):
        return default


def shape_search_event(
    params: Mapping[str, str], *, capture_query_text: bool = False
) -> dict[str, Any]:
    """Attributes for a `GET /api/colas` call, with free text reduced away."""
    used = [k for k in FILTER_KEYS if (params.get(k) or "").strip()]
    q = (params.get("q") or "").strip()

    attrs: dict[str, Any] = {
        "filters_used": ",".join(used),
        "filter_count": len(used),
        "sort": params.get("sort") or "relevance",
        "page": _int(params, "page", 1),
        "page_size": _int(params, "pageSize", 24),
        "facets_requested": (params.get("facets") or "true").lower() != "false",
        "has_query": bool(q),
        "query_length": len(q),
        "term_count": len(q.split()) if q else 0,
    }
    for key in FILTER_VALUE_KEYS:
        value = (params.get(key) or "").strip()
        if value:
            attrs[key] = value[:64]
    if capture_query_text and q:
        attrs["query_text"] = q[:200]
    return attrs


def shape_similar_event(params: Mapping[str, str]) -> dict[str, Any]:
    return {
        "scope": params.get("scope") or "all",
        "limit": _int(params, "limit", 12),
    }


def shape_detail_event(path_params: Mapping[str, Any]) -> dict[str, Any]:
    """Attributes for a detail view. The id is public data, not an identifier."""
    cola_id = str(path_params.get("cola_id") or "").strip()
    return {"cola_id": cola_id[:32]} if cola_id else {}


def shape_image_search_event(
    content_length: int | None, content_type: str | None
) -> dict[str, Any]:
    return {
        "upload_size": size_bucket(content_length),
        "content_type": (content_type or "unknown").split(";")[0][:64],
    }


# logging raises KeyError if `extra` shadows a LogRecord field, so anything that
# collides gets prefixed rather than dropping the event.
_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


def build_record(name: str, attrs: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build the LogRecord `extra` payload for one event."""
    payload: dict[str, Any] = {
        "event": name,
        # Promotes the record into the Application Insights customEvents table.
        "microsoft.custom_event.name": name,
    }
    for key, value in (attrs or {}).items():
        if key in _RESERVED or key in payload:
            key = f"prop_{key}"
        payload[key] = value[:200] if isinstance(value, str) else value
    return payload


def emit(name: str, attrs: Mapping[str, Any] | None = None) -> None:
    """Write one analytics event. Never raises into the caller."""
    try:
        logger.info(name, extra=build_record(name, attrs))
    except Exception:  # pragma: no cover - telemetry must never break a request
        pass
