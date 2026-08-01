"""Reference data for search dropdowns (commodities, sources, origins, statuses)."""
from __future__ import annotations

from fastapi import APIRouter

from ..db import fetch_all
from ..mappers import COMMODITY_LABEL
from ..models import ReferenceData

router = APIRouter(tags=["reference"])

# Fixed display order matching the UI.
CATEGORIES = ["Wine", "Malt Beverage", "Distilled Spirits"]
SOURCES = ["Domestic", "Imported"]


@router.get("/reference", response_model=ReferenceData)
async def reference() -> ReferenceData:
    origin_rows = await fetch_all(
        "SELECT DISTINCT origin, ct_source FROM vw_colas "
        "WHERE origin IS NOT NULL AND btrim(origin) <> '' ORDER BY origin"
    )
    domestic = [r["origin"] for r in origin_rows if (r.get("ct_source") or "") == "domestic"]
    imported = [r["origin"] for r in origin_rows if (r.get("ct_source") or "") != "domestic"]

    status_rows = await fetch_all(
        "SELECT DISTINCT status FROM vw_colas "
        "WHERE status IS NOT NULL AND btrim(status) <> '' ORDER BY status"
    )
    statuses = [r["status"] for r in status_rows]

    # Only advertise commodities that actually occur, in canonical order.
    commodity_rows = await fetch_all("SELECT DISTINCT ct_commodity FROM vw_colas")
    present = {(r.get("ct_commodity") or "").lower() for r in commodity_rows}
    categories = [
        COMMODITY_LABEL[c] for c in ("wine", "beer", "distilled_spirits") if c in present
    ] or CATEGORIES

    return ReferenceData(
        categories=categories,
        sources=SOURCES,
        statuses=statuses,
        domestic_origins=domestic,
        imported_origins=imported,
    )
