"""Usage dashboard queries against Log Analytics.

The KQL below is fixed at import time. Nothing a caller supplies is ever
interpolated into a query: the only knob is the time range, which is resolved
through :data:`RANGES` into a ``timedelta``. That is the injection boundary for
this module, and it is deliberately the only one.

Raw search text is never projected, even when ``analytics_capture_query_text``
is enabled, so turning that setting on cannot leak user input into the page.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any

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

# Bucket width per range, so a chart never returns hundreds of points.
_BUCKETS: dict[str, str] = {"7d": "6h", "14d": "12h", "30d": "1d", "90d": "1d"}

_SERVER_EVENTS = '"search_performed", "detail_viewed", "similar_requested", "image_search_performed"'


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
    """Run every panel query in one batch.

    Returns the rows per panel plus the names that errored. A panel that simply
    matched nothing comes back as an empty list and is *not* reported as failed,
    so the UI can tell "no data yet" from "we could not ask".
    """
    from azure.monitor.query import LogsBatchQuery

    workspace = settings.log_analytics_workspace_id
    if not workspace:
        raise RuntimeError("LOG_ANALYTICS_WORKSPACE_ID is not configured")

    timespan = RANGES[range_key]
    queries = _queries(_BUCKETS[range_key])
    names = list(queries)

    batch = [
        LogsBatchQuery(workspace_id=workspace, query=queries[name], timespan=timespan)
        for name in names
    ]
    results = await _get_client().query_batch(batch)

    panels: dict[str, list[dict[str, Any]]] = {}
    failed: list[str] = []
    for name, result in zip(names, results):
        if isinstance(result, Exception) or getattr(result, "tables", None) is None:
            logger.warning("analytics panel %s failed: %s", name, result)
            panels[name] = []
            failed.append(name)
            continue
        panels[name] = _rows(result)
    return panels, failed


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------
_cache: dict[str, tuple[float, Any]] = {}
_locks: dict[str, asyncio.Lock] = {}


def cached(range_key: str, ttl: float) -> Any | None:
    entry = _cache.get(range_key)
    if entry is not None and time.monotonic() - entry[0] < ttl:
        return entry[1]
    return None


def store(range_key: str, value: Any) -> None:
    _cache[range_key] = (time.monotonic(), value)


def lock_for(range_key: str) -> asyncio.Lock:
    """One in-flight refresh per range; the rest wait rather than re-query."""
    lock = _locks.get(range_key)
    if lock is None:
        lock = _locks[range_key] = asyncio.Lock()
    return lock


def reset_cache() -> None:
    _cache.clear()
