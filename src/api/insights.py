"""Usage dashboard queries against Log Analytics.

The KQL below is fixed at import time. Nothing a caller supplies is ever
interpolated into a query: the only knobs are the time range, resolved through
:data:`RANGES` into a ``timedelta``, and the chart interval, resolved through
:data:`INTERVALS` into a fixed bucket expression. Those two lookups are the
injection boundary for this module, and deliberately the only ones.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from .analytics import FILTER_KEYS, TEXT_FILTER_KEYS
from .config import Settings

logger = logging.getLogger(__name__)

# Range key -> lookback. Retention caps the longest option; see the table
# retention block in infra/main.bicep.
RANGES: dict[str, timedelta] = {
    "7d": timedelta(days=7),
    "14d": timedelta(days=14),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}

DEFAULT_RANGE = "30d"

# Chart interval key -> bucket width. The dashboard reuses these to fill the
# buckets KQL omits when nothing happened.
BUCKET_WIDTHS: dict[str, timedelta] = {
    "6h": timedelta(hours=6),
    "12h": timedelta(hours=12),
    "1d": timedelta(days=1),
    "1w": timedelta(weeks=1),
}

# Interval key -> KQL bucket expression. Weeks follow the calendar (Sunday,
# 00:00 UTC) rather than bin()'s fixed 7-day grid, which starts on a Thursday.
_BUCKETS: dict[str, str] = {
    "6h": "bin(TimeGenerated, 6h)",
    "12h": "bin(TimeGenerated, 12h)",
    "1d": "bin(TimeGenerated, 1d)",
    "1w": "startofweek(TimeGenerated)",
}

# Intervals offered per range, default first, so a chart never returns hundreds
# of points nor collapses to two.
INTERVALS: dict[str, tuple[str, ...]] = {
    "7d": ("6h", "1d"),
    "14d": ("12h", "1d"),
    "30d": ("1d", "1w"),
    "90d": ("1d", "1w"),
}


def resolve_interval(range_key: str, interval: str | None) -> str:
    """The interval to chart a range at; ``None`` means the range's default.

    Raises ``ValueError`` for an interval the range does not offer.
    """
    allowed = INTERVALS[range_key]
    if interval is None:
        return allowed[0]
    if interval not in allowed:
        raise ValueError(f"interval {interval!r} is not offered for range {range_key!r}")
    return interval


def cache_key(range_key: str, interval: str) -> str:
    return f"{range_key}:{interval}"

_SERVER_EVENTS = '"search_performed", "detail_viewed", "similar_requested", "image_search_performed"'

# Dates are ranges, not values worth listing.
_RANKED_FILTERS = ", ".join(
    f'"{k}"' for k in TEXT_FILTER_KEYS if not k.endswith(("From", "To"))
)

# Endpoints charted over time; more lines than this stop being readable.
LATENCY_SERIES_LIMIT = 6

# Rows in each of the recent lists (keyword searches, filter values, artwork
# descriptions).
RECENT_QUERIES_LIMIT = 50

# Every filter a search can carry, so the list can tell apart the same keyword
# under different filters. One plain column each, prefixed so none collides with
# the fixed columns.
RECENT_FILTER_KEYS = tuple(k for k in FILTER_KEYS if k != "q")
RECENT_FILTER_PREFIX = "f_"
_RECENT_FILTER_COLUMNS = ",\n                ".join(
    f'{RECENT_FILTER_PREFIX}{k} = tostring(Properties["{k}"])' for k in RECENT_FILTER_KEYS
)

# Distinct visitors, ignoring events from before visitor ids were recorded (or
# while they were switched off) rather than counting those as zero-id visitors.
_VISITORS = (
    "dcountif(tostring(Properties.visitor_id), "
    "isnotempty(tostring(Properties.visitor_id)))"
)

# Log Analytics runs at most 5 queries at once per identity and queues the rest.
QUERY_CONCURRENCY = 5


def _queries(bucket: str) -> dict[str, str]:
    """Panel name -> KQL. `bucket` is a _BUCKETS value, never from a caller."""
    return {
        # --- Headline usage -------------------------------------------------
        "totals": f"""
            AppEvents
            | where Name in ({_SERVER_EVENTS})
            | summarize
                searches = countif(Name == "search_performed"),
                detailViews = countif(Name == "detail_viewed"),
                similarRequests = countif(Name == "similar_requested"),
                imageSearches = countif(Name == "image_search_performed"),
                sessions = dcount(tostring(Properties.session_id)),
                visitors = {_VISITORS}
        """,
        "usage_over_time": f"""
            AppEvents
            | where Name in ("search_performed", "detail_viewed")
            | summarize
                searches = countif(Name == "search_performed"),
                detailViews = countif(Name == "detail_viewed"),
                sessions = dcount(tostring(Properties.session_id)),
                visitors = {_VISITORS}
              by TimeGenerated = {bucket}
            | order by TimeGenerated asc
        """,
        # --- Search quality -------------------------------------------------
        "zero_results_over_time": f"""
            AppEvents
            | where Name == "search_performed"
            | summarize
                searches = count(),
                zero = countif(tobool(Properties.zero_results))
              by TimeGenerated = {bucket}
            | order by TimeGenerated asc
        """,
        "filter_usage": """
            AppEvents
            | where Name == "search_performed"
            | extend used = split(tostring(Properties.filters_used), ",")
            | mv-expand filter = used to typeof(string)
            | where isnotempty(filter)
            | summarize count() by filter
            | top 15 by count_ desc
        """,
        "paging_depth": """
            AppEvents
            | where Name == "search_performed"
            | summarize count() by page = tostring(toint(Properties.page))
            | top 10 by count_ desc
        """,
        "sort_usage": """
            AppEvents
            | where Name == "search_performed"
            | summarize count() by sort = tostring(Properties.sort)
            | top 10 by count_ desc
        """,
        # Page 1 only: paging through one query should list it once.
        "recent_queries": f"""
            AppEvents
            | where Name == "search_performed" and toint(Properties.page) == 1
            | extend query = tostring(Properties.query_text)
            | where isnotempty(query)
            | top {RECENT_QUERIES_LIMIT} by TimeGenerated desc
            | project
                TimeGenerated,
                query,
                results = toint(Properties.result_total),
                capped = tobool(Properties.total_is_capped),
                sort = tostring(Properties.sort),
                {_RECENT_FILTER_COLUMNS}
        """,
        "zero_result_queries": """
            AppEvents
            | where Name == "search_performed" and tobool(Properties.zero_results)
            | extend query = tolower(tostring(Properties.query_text))
            | where isnotempty(query)
            | summarize count() by query
            | top 15 by count_ desc
        """,
        # One row per distinct value (case-folded), stamped with its latest use
        # and keeping the casing it was last typed in. The result count is that
        # latest search's total, so it reflects whatever else it was combined with.
        "recent_filter_values": f"""
            AppEvents
            | where Name == "search_performed" and toint(Properties.page) == 1
            | mv-expand filter = dynamic([{_RANKED_FILTERS}]) to typeof(string)
            | extend
                value = tostring(Properties[filter]),
                results = toint(Properties.result_total),
                capped = tobool(Properties.total_is_capped)
            | where isnotempty(value)
            | summarize arg_max(TimeGenerated, value, results, capped), count()
              by filter, key = tolower(value)
            | top {RECENT_QUERIES_LIMIT} by TimeGenerated desc
            | project TimeGenerated, filter, value, results, capped, count_
        """,
        "recent_describe_queries": f"""
            AppEvents
            | where Name == "describe_search_performed"
            | extend
                query = tostring(Properties.query_text),
                commodity = tostring(Properties.commodity),
                results = toint(Properties.result_total)
            | where isnotempty(query)
            | summarize arg_max(TimeGenerated, query, results), count()
              by key = tolower(query), commodity
            | top {RECENT_QUERIES_LIMIT} by TimeGenerated desc
            | project TimeGenerated, query, commodity, results, count_
        """,
        # --- Content insights -----------------------------------------------
        "top_colas": """
            AppEvents
            | where Name == "detail_viewed"
            | extend colaId = tostring(Properties.cola_id)
            | where isnotempty(colaId)
            | summarize count() by colaId
            | top 10 by count_ desc
        """,
        "commodity_usage": """
            AppEvents
            | where Name == "search_performed"
            | extend commodity = tostring(Properties.commodity)
            | where isnotempty(commodity)
            | summarize count() by commodity
            | top 10 by count_ desc
        """,
        "origin_usage": """
            AppEvents
            | where Name == "search_performed"
            | extend origin = tostring(Properties.origin)
            | where isnotempty(origin)
            | summarize count() by origin
            | top 10 by count_ desc
        """,
        # --- Operational health ---------------------------------------------
        "latency": """
            AppRequests
            | summarize
                requests = count(),
                p50 = percentile(DurationMs, 50),
                p95 = percentile(DurationMs, 95),
                p99 = percentile(DurationMs, 99)
              by endpoint = Name
            | top 12 by p95 desc
        """,
        "latency_over_time": f"""
            let busiest = AppRequests
                | where Name contains " /api/" and Name != "POST /api/events"
                | summarize n = count() by Name
                | top {LATENCY_SERIES_LIMIT} by n desc
                | project Name;
            AppRequests
            | where Name in (busiest)
            | summarize
                requests = count(),
                p50 = percentile(DurationMs, 50),
                p95 = percentile(DurationMs, 95)
              by TimeGenerated = {bucket}, endpoint = Name
            | order by TimeGenerated asc
        """,
        "reliability": f"""
            AppRequests
            | summarize total = count(), failed = countif(Success == false)
              by TimeGenerated = {bucket}
            | order by TimeGenerated asc
        """,
        "status_codes": """
            AppRequests
            | where toint(ResultCode) >= 400
            | summarize count() by code = tostring(ResultCode)
            | top 10 by count_ desc
        """,
        # --- Image search -----------------------------------------------------
        "image_search_over_time": f"""
            AppEvents
            | where Name in ("image_search_performed", "image_search_abandoned", "image_search_state_lost")
            | summarize
                performed = countif(Name == "image_search_performed"),
                abandoned = countif(Name == "image_search_abandoned"),
                stateLost = countif(Name == "image_search_state_lost")
              by TimeGenerated = {bucket}
            | order by TimeGenerated asc
        """,
        "upload_sizes": """
            AppEvents
            | where Name == "image_search_performed"
            | summarize count() by bucket = tostring(Properties.upload_size)
            | order by count_ desc
        """,
        # --- Map ---------------------------------------------------------------
        "map_over_time": f"""
            AppEvents
            | where Name in ("map_viewport_loaded", "map_area_summarized", "map_marker_clicked")
            | summarize
                viewports = countif(Name == "map_viewport_loaded"),
                areas = countif(Name == "map_area_summarized"),
                markers = countif(Name == "map_marker_clicked"),
                sessions = dcount(tostring(Properties.session_id))
              by TimeGenerated = {bucket}
            | order by TimeGenerated asc
        """,
        # Panning fires a viewport load per stop, so counting events would say
        # more about how the map is dragged than about which reading is used.
        # Sessions is the honest denominator here.
        "map_mode_usage": """
            AppEvents
            | where Name == "map_viewport_loaded"
            | extend reading = strcat(tostring(Properties.mode), " \u00b7 ", tostring(Properties.role))
            | where reading != " \u00b7 "
            | summarize count_ = dcount(tostring(Properties.session_id)) by reading
            | top 10 by count_ desc
        """,
        "map_filter_usage": """
            AppEvents
            | where Name == "map_viewport_loaded"
            | extend used = split(tostring(Properties.filters_used), ",")
            | mv-expand filter = used to typeof(string)
            | where isnotempty(filter)
            | summarize count() by filter
            | top 10 by count_ desc
        """,
        "map_zoom_usage": """
            AppEvents
            | where Name == "map_viewport_loaded"
            | summarize count() by zoom = tostring(toint(Properties.zoom))
            | order by toint(zoom) asc
        """,
    }


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------
_client: Any | None = None
_credential: Any | None = None


def _get_client() -> Any:
    global _client, _credential
    if _client is None:
        from azure.identity.aio import DefaultAzureCredential
        from azure.monitor.query.aio import LogsQueryClient

        _credential = DefaultAzureCredential()
        _client = LogsQueryClient(_credential)
    return _client


async def close_insights() -> None:
    global _client, _credential
    if _client is not None:
        await _client.close()
        _client = None
    if _credential is not None:
        await _credential.close()
        _credential = None


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------
def _rows(result: Any) -> list[dict[str, Any]]:
    """Flatten a Log Analytics result into dicts, or [] if the query failed."""
    tables = getattr(result, "tables", None)
    if not tables:
        return []
    table = tables[0]
    columns = list(table.columns)
    return [dict(zip(columns, row)) for row in table.rows]


async def run_panels(
    settings: Settings, range_key: str, interval: str | None = None
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """Run every panel query, each under its own timeout.

    Charts are bucketed at ``interval`` (a key of :data:`INTERVALS` for the
    range), or at the range's default when it is ``None``.

    Not ``query_batch``: the $batch endpoint answers only when its slowest
    member does, and in production that took 80-200 s while each query ran in
    under 0.2 s. A panel that times out twice is reported failed, not waited on.

    Returns the rows per panel plus the names that errored. A panel that simply
    matched nothing comes back as an empty list and is *not* reported as failed,
    so the UI can tell "no data yet" from "we could not ask".
    """
    workspace = settings.log_analytics_workspace_id
    if not workspace:
        raise RuntimeError("LOG_ANALYTICS_WORKSPACE_ID is not configured")

    timespan = RANGES[range_key]
    queries = _queries(_BUCKETS[resolve_interval(range_key, interval)])
    names = list(queries)
    client = _get_client()
    gate = asyncio.Semaphore(QUERY_CONCURRENCY)
    timeout = settings.analytics_panel_timeout_seconds

    async def one(query: str) -> Any:
        # A hung query is luck of the draw, not load: the retry usually returns at once.
        for attempt in range(2):
            async with gate:
                try:
                    return await asyncio.wait_for(
                        client.query_workspace(
                            workspace, query, timespan=timespan, server_timeout=timeout
                        ),
                        timeout,
                    )
                except TimeoutError:
                    if attempt:
                        raise

    results = await asyncio.gather(
        *(one(queries[name]) for name in names), return_exceptions=True
    )

    panels: dict[str, list[dict[str, Any]]] = {}
    failed: list[str] = []
    for name, result in zip(names, results):
        if isinstance(result, Exception) or getattr(result, "tables", None) is None:
            logger.warning("analytics panel %s failed: %r", name, result)
            panels[name] = []
            failed.append(name)
            continue
        panels[name] = _rows(result)
    return panels, failed


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------
_cache: dict[str, tuple[float, Any]] = {}
_refreshes: dict[str, asyncio.Task[Any]] = {}


def lookup(key: str, ttl: float) -> tuple[Any, bool] | None:
    """The cached value for a key (see :func:`cache_key`) and whether it is past its TTL."""
    entry = _cache.get(key)
    if entry is None:
        return None
    stamp, value = entry
    return value, time.monotonic() - stamp >= ttl


def store(key: str, value: Any, *, complete: bool = True) -> None:
    # An incomplete result is still served, but counts as stale straight away.
    _cache[key] = (time.monotonic() if complete else float("-inf"), value)


def refresh(
    key: str, build: Callable[[], Awaitable[tuple[Any, bool]]]
) -> asyncio.Task[Any]:
    """One in-flight rebuild per cache key; later callers share it.

    ``build`` returns the value and whether it is complete.
    """
    task = _refreshes.get(key)
    if task is not None and not task.done():
        return task

    async def run() -> Any:
        value, complete = await build()
        store(key, value, complete=complete)
        return value

    def finished(done: asyncio.Task[Any]) -> None:
        if not done.cancelled() and done.exception() is not None:
            logger.warning(
                "analytics refresh failed for %s", key, exc_info=done.exception()
            )

    task = _refreshes[key] = asyncio.ensure_future(run())
    task.add_done_callback(finished)
    return task


def reset_cache() -> None:
    _cache.clear()
    _refreshes.clear()
