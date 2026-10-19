"""Usage dashboard queries against Log Analytics.

The KQL below is fixed at import time. Nothing a caller supplies is ever
interpolated into a query: the only knob is the time range, which is resolved
through :data:`RANGES` into a ``timedelta``. That is the injection boundary for
this module, and it is deliberately the only one.
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

# Bucket width per range, so a chart never returns hundreds of points. The
# dashboard reuses these to fill the buckets KQL omits when nothing happened.
BUCKET_WIDTHS: dict[str, timedelta] = {
    "7d": timedelta(hours=6),
    "14d": timedelta(hours=12),
    "30d": timedelta(days=1),
    "90d": timedelta(days=1),
}

_BUCKETS: dict[str, str] = {
    key: f"{int(width.total_seconds())}s" for key, width in BUCKET_WIDTHS.items()
}

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

# Log Analytics runs at most 5 queries at once per identity and queues the rest.
QUERY_CONCURRENCY = 5


def _queries(bucket: str) -> dict[str, str]:
    """Panel name -> KQL. `bucket` comes from _BUCKETS, never from a caller."""
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
                sessions = dcount(tostring(Properties.session_id))
        """,
        "usage_over_time": f"""
            AppEvents
            | where Name in ("search_performed", "detail_viewed")
            | summarize
                searches = countif(Name == "search_performed"),
                detailViews = countif(Name == "detail_viewed"),
                sessions = dcount(tostring(Properties.session_id))
              by bin(TimeGenerated, {bucket})
            | order by TimeGenerated asc
        """,
        # --- Search quality -------------------------------------------------
        "zero_results_over_time": f"""
            AppEvents
            | where Name == "search_performed"
            | summarize
                searches = count(),
                zero = countif(tobool(Properties.zero_results))
              by bin(TimeGenerated, {bucket})
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
        # and keeping the casing it was last typed in.
        "recent_filter_values": f"""
            AppEvents
            | where Name == "search_performed" and toint(Properties.page) == 1
            | mv-expand filter = dynamic([{_RANKED_FILTERS}]) to typeof(string)
            | extend value = tostring(Properties[filter])
            | where isnotempty(value)
            | summarize arg_max(TimeGenerated, value), count() by filter, key = tolower(value)
            | top {RECENT_QUERIES_LIMIT} by TimeGenerated desc
            | project TimeGenerated, filter, value, count_
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
              by bin(TimeGenerated, {bucket}), endpoint = Name
            | order by TimeGenerated asc
        """,
        "reliability": f"""
            AppRequests
            | summarize total = count(), failed = countif(Success == false)
              by bin(TimeGenerated, {bucket})
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
              by bin(TimeGenerated, {bucket})
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
              by bin(TimeGenerated, {bucket})
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
    settings: Settings, range_key: str
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """Run every panel query, each under its own timeout.

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
    queries = _queries(_BUCKETS[range_key])
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


def lookup(range_key: str, ttl: float) -> tuple[Any, bool] | None:
    """The cached value for a range and whether it is past its TTL."""
    entry = _cache.get(range_key)
    if entry is None:
        return None
    stamp, value = entry
    return value, time.monotonic() - stamp >= ttl


def store(range_key: str, value: Any, *, complete: bool = True) -> None:
    # An incomplete result is still served, but counts as stale straight away.
    _cache[range_key] = (time.monotonic() if complete else float("-inf"), value)


def refresh(
    range_key: str, build: Callable[[], Awaitable[tuple[Any, bool]]]
) -> asyncio.Task[Any]:
    """One in-flight rebuild per range; later callers share it.

    ``build`` returns the value and whether it is complete.
    """
    task = _refreshes.get(range_key)
    if task is not None and not task.done():
        return task

    async def run() -> Any:
        value, complete = await build()
        store(range_key, value, complete=complete)
        return value

    def finished(done: asyncio.Task[Any]) -> None:
        if not done.cancelled() and done.exception() is not None:
            logger.warning(
                "analytics refresh failed for %s", range_key, exc_info=done.exception()
            )

    task = _refreshes[range_key] = asyncio.ensure_future(run())
    task.add_done_callback(finished)
    return task


def reset_cache() -> None:
    _cache.clear()
    _refreshes.clear()
