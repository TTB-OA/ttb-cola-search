"""Unlisted usage dashboard.

Serves aggregate numbers only — counts, rates and percentiles read back out of
Log Analytics. No row here identifies a person: the underlying events carry a
pseudonymous session id and nothing else.

The endpoint is off unless ``analytics_dashboard_enabled`` is set, and returns
404 (not 403) when off so a disabled deployment leaks nothing about its
existence. Unlisted is not access control; see the README before exposing this
on a production hostname.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request

from .. import insights
from ..config import Settings, get_settings
from ..db import fetch_all
from ..mappers import SEARCH_TABLE
from ..models import (
    DashboardData,
    DashboardPanels,
    DashboardTotals,
    LatencyRow,
    NamedCount,
    TimePoint,
    TopCola,
)
from ..ratelimit import SlidingWindowLimiter, client_key

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analytics"])

RangeKey = Literal["7d", "14d", "30d", "90d"]

_limiter: SlidingWindowLimiter | None = None


def _dashboard_limiter(settings: Settings) -> SlidingWindowLimiter:
    global _limiter
    if _limiter is None:
        _limiter = SlidingWindowLimiter(
            settings.analytics_dashboard_rate_limit,
            settings.analytics_dashboard_rate_window_seconds,
        )
    return _limiter


# ---------------------------------------------------------------------------
# Row shaping
# ---------------------------------------------------------------------------
def _num(value: Any) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


def _counts(rows: list[dict[str, Any]], key: str) -> list[NamedCount]:
    out = []
    for row in rows:
        label = str(row.get(key) or "").strip()
        if label:
            out.append(NamedCount(label=label[:64], count=int(row.get("count_") or 0)))
    return out


def _series(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> list[TimePoint]:
    points = []
    for row in rows:
        when = row.get("TimeGenerated")
        if when is None:
            continue
        points.append(
            TimePoint(t=when, values={f: _num(row.get(f)) for f in fields})
        )
    return points


def _rate(rows: list[dict[str, Any]], numerator: str, denominator: str) -> float:
    total = sum(int(r.get(denominator) or 0) for r in rows)
    if not total:
        return 0.0
    hit = sum(int(r.get(numerator) or 0) for r in rows)
    return round(hit / total * 100, 1)


async def _enrich_colas(rows: list[dict[str, Any]]) -> list[TopCola]:
    """Attach brand names to the most-viewed ids. Ids come from our own events."""
    ranked: list[TopCola] = []
    for row in rows[:10]:
        cola_id = str(row.get("colaId") or "").strip()
        if cola_id.isdigit():
            ranked.append(TopCola(cola_id=cola_id, views=int(row.get("count_") or 0)))
    if not ranked:
        return []

    try:
        found = await fetch_all(
            f"""--sql
            SELECT cola_id, brand_name, origin
              FROM {SEARCH_TABLE}
             WHERE cola_id = ANY(%s)
            """,
            ([int(c.cola_id) for c in ranked],),
        )
    except Exception:  # noqa: BLE001 - names are a nicety, ids already work
        logger.warning("could not resolve top COLA names", exc_info=True)
        return ranked

    by_id = {str(r["cola_id"]): r for r in found}
    for item in ranked:
        match = by_id.get(item.cola_id)
        if match:
            item.brand_name = match.get("brand_name")
            item.origin = match.get("origin")
    return ranked


async def _build(settings: Settings, range_key: str) -> DashboardData:
    panels, unavailable = await insights.run_panels(settings, range_key)

    totals_rows = panels.get("totals") or [{}]
    head = totals_rows[0]
    latency_rows = panels.get("latency") or []

    totals = DashboardTotals(
        searches=int(head.get("searches") or 0),
        detail_views=int(head.get("detailViews") or 0),
        similar_requests=int(head.get("similarRequests") or 0),
        image_searches=int(head.get("imageSearches") or 0),
        sessions=int(head.get("sessions") or 0),
        zero_result_rate=_rate(panels.get("zero_results_over_time") or [], "zero", "searches"),
        # No availability test is configured, so this is a request failure rate,
        # not uptime. Labelled as such in the UI.
        failure_rate=_rate(panels.get("reliability") or [], "failed", "total"),
        p95_ms=max((_num(r.get("p95")) for r in latency_rows), default=0.0),
    )

    built = DashboardPanels(
        usage_over_time=_series(
            panels.get("usage_over_time") or [], ("searches", "detailViews", "sessions")
        ),
        zero_results_over_time=_series(
            panels.get("zero_results_over_time") or [], ("searches", "zero")
        ),
        filter_usage=_counts(panels.get("filter_usage") or [], "filter"),
        paging_depth=_counts(panels.get("paging_depth") or [], "page"),
        sort_usage=_counts(panels.get("sort_usage") or [], "sort"),
        top_colas=await _enrich_colas(panels.get("top_colas") or []),
        commodity_usage=_counts(panels.get("commodity_usage") or [], "commodity"),
        origin_usage=_counts(panels.get("origin_usage") or [], "origin"),
        latency=[
            LatencyRow(
                endpoint=str(r.get("endpoint") or "")[:80],
                requests=int(r.get("requests") or 0),
                p50=_num(r.get("p50")),
                p95=_num(r.get("p95")),
                p99=_num(r.get("p99")),
            )
            for r in latency_rows
        ],
        reliability=_series(panels.get("reliability") or [], ("total", "failed")),
        status_codes=_counts(panels.get("status_codes") or [], "code"),
        image_search_over_time=_series(
            panels.get("image_search_over_time") or [],
            ("performed", "abandoned", "stateLost"),
        ),
        upload_sizes=_counts(panels.get("upload_sizes") or [], "bucket"),
    )

    return DashboardData(
        range=range_key,
        generated_at=datetime.now(timezone.utc),
        totals=totals,
        panels=built,
        unavailable=unavailable,
    )


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------
@router.get("/analytics/dashboard", response_model=DashboardData)
async def dashboard(request: Request, range: RangeKey = "30d") -> DashboardData:
    settings = get_settings()
    if not settings.analytics_dashboard_enabled:
        raise HTTPException(status_code=404, detail="Not found.")

    if _dashboard_limiter(settings).check(
        client_key(request, settings.trust_forwarded_for)
    ) is not None:
        raise HTTPException(status_code=429, detail="Too many requests.")

    ttl = settings.analytics_dashboard_cache_seconds
    hit = insights.cached(range, ttl)
    if hit is not None:
        return hit.model_copy(update={"cached": True})

    # One refresh per range at a time; a burst of cold requests otherwise turns
    # into a burst of billed Log Analytics queries.
    async with insights.lock_for(range):
        hit = insights.cached(range, ttl)
        if hit is not None:
            return hit.model_copy(update={"cached": True})
        try:
            data = await _build(settings, range)
        except Exception as exc:  # noqa: BLE001
            logger.warning("dashboard query failed: %s", exc, exc_info=True)
            raise HTTPException(
                status_code=503, detail="Usage data is unavailable right now."
            ) from exc
        insights.store(range, data)
        return data
