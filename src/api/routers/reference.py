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

# Distinct-value roll-ups still cost a full scan, so serve them from process
# memory between refreshes rather than on every SPA load.
CACHE_TTL_SECONDS = 3600
_cache: tuple[float, ReferenceData] | None = None


async def _load_reference() -> ReferenceData:
    # Single materialised CTE so the table is scanned once for all dimensions.
    rows = await fetch_all(
        f"""--sql
        WITH m AS (
          SELECT origin, ct_source, status, ct_commodity, primary_permit_state_addr
          FROM {SEARCH_TABLE}
        )
        SELECT 'origin' AS dim, origin AS value, max(ct_source) AS extra FROM m
          WHERE origin IS NOT NULL AND btrim(origin) <> '' GROUP BY 1, 2
        UNION ALL
        SELECT 'status', status, NULL::text FROM m
          WHERE status IS NOT NULL AND btrim(status) <> '' GROUP BY 1, 2
        UNION ALL
        SELECT 'commodity', ct_commodity, NULL::text FROM m
          WHERE ct_commodity IS NOT NULL GROUP BY 1, 2
        UNION ALL
        SELECT 'permitState', upper(primary_permit_state_addr), NULL::text FROM m
          WHERE btrim(coalesce(primary_permit_state_addr, '')) <> '' GROUP BY 1, 2
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

    return ReferenceData(
        categories=categories,
        sources=SOURCES,
        statuses=sorted(r["value"] for r in grouped.get("status", [])),
        domestic_origins=domestic,
        imported_origins=imported,
        permit_states=sorted(r["value"] for r in grouped.get("permitState", [])),
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
