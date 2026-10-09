"""Reference data for search dropdowns (commodities, sources, origins, statuses)."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter

from ..db import fetch_all
from ..mappers import APPLICATION_TYPES, COMMODITY_LABEL, SEARCH_TABLE
from ..models import ReferenceData

logger = logging.getLogger(__name__)

router = APIRouter(tags=["reference"])

# Fixed display order matching the UI.
CATEGORIES = ["Wine", "Malt Beverage", "Distilled Spirits"]
SOURCES = ["Domestic", "Imported"]

# Distinct-value roll-ups are cheap per call but not free, so serve them from
# process memory between refreshes rather than on every SPA load.
CACHE_TTL_SECONDS = 3600
_cache: tuple[float, ReferenceData] | None = None

# Counting class/types is a full pass over cola_search (15-42 s measured), so it
# runs in the background and is kept for a day; the counts drift slowly.
CLASS_COUNT_TTL_SECONDS = 24 * 3600
CLASS_COUNT_TIMEOUT_MS = 180_000
_class_counts: tuple[float, dict[str, int]] | None = None
_class_count_task: asyncio.Task[None] | None = None


def _loose_distinct(cte: str, expr: str) -> str:
    """Distinct values of `expr` via a loose index scan ("skip scan").

    Each expression below leads a btree on the search table, so the walk jumps
    from one distinct value to the next instead of aggregating every row. A
    plain GROUP BY here is a 3M-row sequential scan that blows the statement
    timeout. `cte` must be the name this body is bound to, so the recursive
    term references itself.
    """
    return f"""
        (SELECT {expr} AS v FROM {SEARCH_TABLE}
          WHERE {expr} IS NOT NULL ORDER BY 1 LIMIT 1)
        UNION ALL
        SELECT (SELECT {expr} FROM {SEARCH_TABLE}
                 WHERE {expr} > {cte}.v ORDER BY 1 LIMIT 1)
          FROM {cte} WHERE {cte}.v IS NOT NULL
    """


async def _load_lookups() -> dict[str, Any]:
    """Controlled vocabularies, read from the small reference tables.

    These are the codes TTB publishes rather than the values observed in
    cola_search, so they cost a few hundred rows instead of a 3M-row roll-up.
    """
    rows = await fetch_all(
        """--sql
        SELECT 'classType' AS dim, description AS value
          FROM ref_product_class_types
         WHERE btrim(coalesce(description, '')) <> ''
        UNION
        SELECT 'received', description
          FROM ref_received_codes
         WHERE btrim(coalesce(description, '')) <> ''
        UNION
        SELECT 'varietal', vartl_name
          FROM ref_grape_varietals
         WHERE btrim(coalesce(vartl_name, '')) <> ''
        """
    )

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["dim"], []).append(row)

    # cola_grape_varietals is small (~150k rows), so this is cheap. Keyed by the
    # vocabulary spelling; the case can differ from the per-COLA rows.
    varietal_counts = {
        r["value"]: int(r["n"])
        for r in await fetch_all(
            """--sql
            SELECT r.vartl_name AS value, c.n
              FROM ref_grape_varietals r
              JOIN (SELECT upper(vartl_name) AS k, count(*) AS n
                      FROM cola_grape_varietals GROUP BY 1) c
                ON c.k = upper(r.vartl_name)
            """
        )
    }

    return {
        "class_types": sorted(r["value"] for r in grouped.get("classType", [])),
        # Descriptions rather than codes, so the value reads in a URL and in the
        # active-filter chips; /colas accepts either.
        "received_types": sorted(r["value"] for r in grouped.get("received", [])),
        "varietals": sorted(r["value"] for r in grouped.get("varietal", [])),
        "varietal_counts": varietal_counts,
    }


async def _load_class_counts() -> dict[str, int]:
    """Records per class/type description, keyed by the vocabulary spelling."""
    rows = await fetch_all(
        f"""--sql
        SELECT r.description AS value, c.n
          FROM (SELECT DISTINCT description FROM ref_product_class_types) r
          JOIN (SELECT upper(class_type) AS k, count(*) AS n
                  FROM {SEARCH_TABLE} WHERE class_type IS NOT NULL GROUP BY 1) c
            ON c.k = upper(r.description)
        """,
        statement_timeout_ms=CLASS_COUNT_TIMEOUT_MS,
        prepare=False,
    )
    return {r["value"]: int(r["n"]) for r in rows}


async def _refresh_class_counts() -> None:
    global _class_counts
    try:
        _class_counts = (time.monotonic(), await _load_class_counts())
    except Exception:
        logger.exception("class/type count refresh failed")


def _class_counts_now() -> dict[str, int]:
    """Cached counts, kicking off a refresh when missing or stale. Never waits."""
    global _class_count_task
    fresh = _class_counts is not None and time.monotonic() - _class_counts[0] < CLASS_COUNT_TTL_SECONDS
    if not fresh and (_class_count_task is None or _class_count_task.done()):
        _class_count_task = asyncio.create_task(_refresh_class_counts())
    return _class_counts[1] if _class_counts else {}


async def _load_reference() -> ReferenceData:
    # origin functionally determines ct_source, so one probe per origin (via the
    # same index) reproduces the old max(ct_source) rollup.
    rows = await fetch_all(
        f"""--sql
        WITH RECURSIVE
        t AS ({_loose_distinct("t", "origin")}),
        s AS ({_loose_distinct("s", "status")}),
        c AS ({_loose_distinct("c", "ct_commodity")}),
        p AS ({_loose_distinct("p", "upper(primary_permit_state_addr::text)")})
        SELECT 'origin' AS dim, t.v AS value, src.ct_source AS extra
          FROM t
          LEFT JOIN LATERAL (
            SELECT ct_source FROM {SEARCH_TABLE} WHERE origin = t.v LIMIT 1
          ) src ON TRUE
          WHERE t.v IS NOT NULL AND btrim(t.v) <> ''
        UNION ALL
        SELECT 'status', s.v, NULL::text FROM s
          WHERE s.v IS NOT NULL AND btrim(s.v) <> ''
        UNION ALL
        SELECT 'commodity', c.v, NULL::text FROM c
          WHERE c.v IS NOT NULL
        UNION ALL
        SELECT 'permitState', p.v, NULL::text FROM p
          WHERE p.v IS NOT NULL AND btrim(p.v) <> ''
        """
    )

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["dim"], []).append(row)

    origins = sorted(grouped.get("origin", []), key=lambda r: r["value"])
    domestic = [r["value"] for r in origins if (r.get("extra") or "") == "domestic"]
    imported = [r["value"] for r in origins if (r.get("extra") or "") != "domestic"]

    # Only advertise commodities that actually occur, in canonical order.
    present = {(r["value"] or "").lower() for r in grouped.get("commodity", [])}
    categories = [
        COMMODITY_LABEL[c] for c in ("wine", "beer", "distilled_spirits") if c in present
    ] or CATEGORIES

    lookups = await _load_lookups()

    return ReferenceData(
        categories=categories,
        sources=SOURCES,
        statuses=sorted(r["value"] for r in grouped.get("status", [])),
        domestic_origins=domestic,
        imported_origins=imported,
        permit_states=sorted(r["value"] for r in grouped.get("permitState", [])),
        # Fixed by the form, so listed in item 14's own order rather than sorted.
        application_types=list(APPLICATION_TYPES),
        **lookups,
    )


@router.get("/reference", response_model=ReferenceData)
async def reference() -> ReferenceData:
    global _cache
    now = time.monotonic()
    if _cache is None or now - _cache[0] >= CACHE_TTL_SECONDS:
        _cache = (now, await _load_reference())
    return _cache[1].model_copy(update={"class_type_counts": _class_counts_now()})
