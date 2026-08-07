"""Pipeline coverage by approval year.

Reads ``cola_coverage_year``, which the materialisation job rebuilds in full on
every run, and reports how far each calendar year of COLAs has progressed
through ingest, detail fill, image download, OCR and embedding. This is a
data-completeness statement about the site, not a measure of TTB activity.

The same job maintains ``cola_search``, so its queue depth is reported here too:
coverage says what the pipeline holds, the index status says how much of it the
search surface has caught up with.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter

from ..db import fetch_all, fetch_one
from ..mappers import COVERAGE_TABLE, DIRTY_TABLE, OCR_TABLE, SEARCH_TABLE
from ..models import (
    CoverageCounts,
    CoverageResponse,
    CoverageYear,
    SearchIndexStatus,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["coverage"])

# The source table changes at most once per pipeline run, so repeated page loads
# are served from process memory rather than hitting the database each time.
CACHE_TTL_SECONDS = 900
_cache: tuple[float, CoverageResponse] | None = None

# Stage columns, in pipeline order, mapped to their response field.
_STAGE_COLUMNS = (
    ("ingested_count", "ingested_cola_count"),
    ("detail_count", "detail_cola_count"),
    ("image_count", "image_cola_count"),
    ("ocr_count", "ocr_cola_count"),
    ("embedding_count", "embedding_cola_count"),
)


# Table names are module constants, never user input, so interpolating them into
# to_regclass() is safe. reltuples is the planner's estimate, refreshed by
# autovacuum; an exact count of these tables is a multi-million-row scan.
_SEARCH_STATUS_SQL = f"""--sql
SELECT (SELECT count(*) FROM {DIRTY_TABLE}) AS pending_count,
       (SELECT min(marked_at) FROM {DIRTY_TABLE}) AS oldest_pending_at,
       (SELECT reltuples::bigint FROM pg_class
         WHERE oid = to_regclass('{SEARCH_TABLE}')) AS searchable_count,
       (SELECT reltuples::bigint FROM pg_class
         WHERE oid = to_regclass('{OCR_TABLE}')) AS label_text_count
"""


def reset_cache() -> None:
    global _cache
    _cache = None


def _count(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _optional_count(value: Any) -> int | None:
    return None if value is None else _count(value)


def _estimate(value: Any) -> int | None:
    """reltuples is -1 for a table that has never been analysed, not empty."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


async def _search_status() -> SearchIndexStatus | None:
    try:
        row = await fetch_one(_SEARCH_STATUS_SQL)
    except Exception:  # noqa: BLE001 - coverage is still worth showing without it
        logger.warning("could not read search index status", exc_info=True)
        return None
    if row is None:
        return None

    stamp = row.get("oldest_pending_at")
    return SearchIndexStatus(
        searchable_count=_estimate(row.get("searchable_count")),
        label_text_count=_estimate(row.get("label_text_count")),
        pending_count=_count(row.get("pending_count")),
        oldest_pending_at=stamp if isinstance(stamp, datetime) else None,
    )


def _year_from_row(row: dict[str, Any]) -> CoverageYear:
    return CoverageYear(
        year=int(row["coverage_year"]),
        api_count=_optional_count(row.get("api_cola_count")),
        **{field: _count(row.get(column)) for field, column in _STAGE_COLUMNS},
    )


def _totals(years: list[CoverageYear]) -> CoverageCounts:
    # api_cola_count is nullable per year; summing over the years that reported
    # one would understate the total, so only publish it when every year has it.
    reported = [y.api_count for y in years if y.api_count is not None]
    return CoverageCounts(
        api_count=sum(reported) if years and len(reported) == len(years) else None,
        **{
            field: sum(getattr(y, field) for y in years)
            for field, _ in _STAGE_COLUMNS
        },
    )


async def _load() -> CoverageResponse:
    rows = await fetch_all(
        f"""--sql
        SELECT coverage_year,
               api_cola_count,
               ingested_cola_count,
               detail_cola_count,
               image_cola_count,
               ocr_cola_count,
               embedding_cola_count,
               _loaded_at
          FROM {COVERAGE_TABLE}
         WHERE coverage_year IS NOT NULL
         ORDER BY coverage_year DESC
        """
    )
    years = [_year_from_row(row) for row in rows]
    stamps = [row.get("_loaded_at") for row in rows]
    as_of = max((s for s in stamps if isinstance(s, datetime)), default=None)
    return CoverageResponse(
        years=years,
        totals=_totals(years),
        search=await _search_status(),
        as_of=as_of,
    )


@router.get("/coverage", response_model=CoverageResponse)
async def coverage() -> CoverageResponse:
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < CACHE_TTL_SECONDS:
        return _cache[1]

    data = await _load()
    _cache = (now, data)
    return data
