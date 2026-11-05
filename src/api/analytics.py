"""Usage analytics event shaping.

Everything here is pure and synchronous so it can be unit tested without a
server, a database, or an exporter. The only side-effecting function is
:func:`emit`, which writes a structured log record that Azure Monitor picks up.

Collection policy: record which filters a user reached for and, while
``analytics_capture_query_text`` is on (the default), what they typed. With it
off, free-text values are reduced to length and term count.
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
    ("GET", "/search/describe"): "describe_search_performed",
    ("GET", "/map/points"): "map_viewport_loaded",
    ("GET", "/map/area"): "map_area_summarized",
}


def route_key(method: str, path: str) -> tuple[str, str]:
    return method, path.removeprefix(API_PREFIX)


# Request header the SPA sets on lookups it makes for itself rather than for a
# search someone typed: the home page's "recently approved" strip and the tour's
# sample record both go through `GET /api/colas`. Those are recorded under their
# own event name so they still count a session but never count as a search.
BACKGROUND_HEADER = "X-Client-Purpose"
BACKGROUND_SEARCH_EVENT = "background_search"


def is_background(request: Any) -> bool:
    headers = getattr(request, "headers", {}) or {}
    return (headers.get(BACKGROUND_HEADER.lower()) or "").strip().lower() == "background"

# Query params that represent a user-applied filter. Names are always recorded;
# values only for FILTER_VALUE_KEYS unless free-text capture is on.
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
    "appellation",
    "formula",
    "submittedFrom",
    "submittedTo",
)

# Closed vocabularies, safe to record verbatim.
FILTER_VALUE_KEYS = ("commodity", "source", "origin", "status")

# User-typed filter values, recorded under their own param name when capture is
# on. `q` is excluded: it is recorded as `query_text`.
TEXT_FILTER_KEYS = tuple(k for k in FILTER_KEYS if k != "q" and k not in FILTER_VALUE_KEYS)

_MAX_TEXT = 200

# Map filters are a subset of the search ones plus the two map-only controls.
MAP_FILTER_KEYS = (
    "commodity",
    "source",
    "origin",
    "classType",
    "varietal",
    "dateFrom",
    "dateTo",
)

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


# Response header ("on" / "off") telling the SPA whether visitor ids are being
# recorded, so it can delete the one it stored and stop minting new ones.
VISITOR_POLICY_HEADER = "X-Analytics-Visitor"


def opted_out(request: Any) -> bool:
    """True when the browser sends Global Privacy Control or Do Not Track."""
    headers = getattr(request, "headers", {}) or {}
    return (headers.get("sec-gpc") or "").strip() == "1" or (
        headers.get("dnt") or ""
    ).strip() == "1"


def visitor_id_from(request: Any, *, session_id: str, enabled: bool) -> str | None:
    """Pseudonymous visitor id, or None when visitor ids are switched off.

    A browser that opted out, or that could not store an id, is counted under
    its session id instead, so it still counts once per session but is never
    linked across sessions.
    """
    if not enabled:
        return None
    if opted_out(request):
        return session_id
    headers = getattr(request, "headers", {}) or {}
    supplied = (headers.get("x-client-visitor") or "").strip().lower()
    return supplied if _UUID_RE.match(supplied) else session_id


def identity_attrs(request: Any, settings: Any) -> dict[str, str]:
    """The session and (when enabled) visitor ids every event carries."""
    session_id = session_id_from(
        request,
        trust_forwarded_for=settings.trust_forwarded_for,
        salt=settings.analytics_salt,
    )
    attrs = {"session_id": session_id}
    visitor_id = visitor_id_from(
        request, session_id=session_id, enabled=settings.analytics_visitor_id_enabled
    )
    if visitor_id is not None:
        attrs["visitor_id"] = visitor_id
    return attrs


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


def _query_shape(q: str) -> dict[str, Any]:
    return {
        "has_query": bool(q),
        "query_length": len(q),
        "term_count": len(q.split()) if q else 0,
    }


def shape_search_event(
    params: Mapping[str, str], *, capture_query_text: bool = False
) -> dict[str, Any]:
    """Attributes for a `GET /api/colas` call."""
    used = [k for k in FILTER_KEYS if (params.get(k) or "").strip()]
    q = (params.get("q") or "").strip()

    attrs: dict[str, Any] = {
        "filters_used": ",".join(used),
        "filter_count": len(used),
        "sort": params.get("sort") or "relevance",
        "page": _int(params, "page", 1),
        "page_size": _int(params, "pageSize", 24),
        "facets_requested": (params.get("facets") or "true").lower() != "false",
        **_query_shape(q),
    }
    for key in FILTER_VALUE_KEYS:
        value = (params.get(key) or "").strip()
        if value:
            attrs[key] = value[:64]
    if capture_query_text:
        if q:
            attrs["query_text"] = q[:_MAX_TEXT]
        for key in TEXT_FILTER_KEYS:
            value = (params.get(key) or "").strip()
            if value:
                attrs[key] = value[:_MAX_TEXT]
    return attrs


def shape_describe_event(
    params: Mapping[str, str], *, capture_query_text: bool = False
) -> dict[str, Any]:
    """Attributes for a `GET /api/search/describe` (text-to-image) call."""
    q = (params.get("q") or "").strip()
    attrs: dict[str, Any] = {"limit": _int(params, "limit", 48), **_query_shape(q)}
    commodity = (params.get("commodity") or "").strip()
    if commodity:
        attrs["commodity"] = commodity[:64]
    if capture_query_text and q:
        attrs["query_text"] = q[:_MAX_TEXT]
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


def shape_map_event(params: Mapping[str, str]) -> dict[str, Any]:
    """Attributes for a map viewport call.

    Zoom is recorded but the viewport itself is not: which part of the country a
    given session was looking at says more about the user than it does about the
    product.
    """
    used = [k for k in MAP_FILTER_KEYS if (params.get(k) or "").strip()]
    attrs: dict[str, Any] = {
        "mode": params.get("mode") or "heat",
        "role": params.get("role") or "primary_premise",
        "zoom": _int(params, "zoom", 4),
        "filters_used": ",".join(used),
        "filter_count": len(used),
    }
    for key in FILTER_VALUE_KEYS:
        value = (params.get(key) or "").strip()
        if value:
            attrs[key] = value[:64]
    return attrs


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
