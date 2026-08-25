"""Reference data for search dropdowns (commodities, sources, origins, statuses)."""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter

from ..db import fetch_all
from ..mappers import COMMODITY_LABEL, SEARCH_TABLE
from ..models import ReferenceData

router = APIRouter(tags=["reference"])

# Fixed display order matching the UI.
CATEGORIES = ["Wine", "Malt Beverage", "Distilled Spirits"]
SOURCES = ["Domestic", "Imported"]

# Distinct-value roll-ups are cheap per call but not free, so serve them from
# process memory between refreshes rather than on every SPA load.
CACHE_TTL_SECONDS = 3600
_cache: tuple[float, ReferenceData] | None = None


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

    return {
        "class_types": sorted(r["value"] for r in grouped.get("classType", [])),
        # Descriptions rather than codes, so the value reads in a URL and in the
        # active-filter chips; /colas accepts either.
        "received_types": sorted(r["value"] for r in grouped.get("received", [])),
        "varietals": sorted(r["value"] for r in grouped.get("varietal", [])),
    }


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
        **lookups,
    )


@router.get("/reference", response_model=ReferenceData)
async def reference() -> ReferenceData:
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < CACHE_TTL_SECONDS:
        return _cache[1]

    data = await _load_reference()
    _cache = (now, data)
    return data
