"""COLA list/search and detail endpoints."""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..db import fetch_all, fetch_one
from ..mappers import (
    COMMODITY_CODE,
    SOURCE_CODE,
    commodity_label,
    detail_from_rows,
    source_label,
    summary_from_row,
)
from ..models import ColaDetail, FacetBucket, Facets, SearchResponse

router = APIRouter(tags=["colas"])

SORTS = {
    "relevance": "completed_date DESC NULLS LAST",
    "approvalDate": "completed_date DESC NULLS LAST",
    "brand": "brand_name ASC NULLS LAST",
}


def _build_filters(
    q: str | None,
    ttb_id: str | None,
    brand: str | None,
    fanciful: str | None,
    commodity: str | None,
    source: str | None,
    origin: str | None,
    status: str | None,
    date_from: date | None,
    date_to: date | None,
) -> tuple[str, list[Any]]:
    conditions: list[str] = []
    params: list[Any] = []

    if q:
        like = f"%{q}%"
        conditions.append(
            "(brand_name ILIKE %s OR fanciful_name ILIKE %s OR applicant_name ILIKE %s "
            "OR class_type ILIKE %s OR origin ILIKE %s OR cola_id::text ILIKE %s "
            "OR serial_num ILIKE %s)"
        )
        params.extend([like] * 7)
    if ttb_id:
        like = f"%{ttb_id}%"
        conditions.append("(cola_id::text ILIKE %s OR serial_num ILIKE %s)")
        params.extend([like, like])
    if brand:
        conditions.append("brand_name ILIKE %s")
        params.append(f"%{brand}%")
    if fanciful:
        conditions.append("fanciful_name ILIKE %s")
        params.append(f"%{fanciful}%")
    if commodity:
        conditions.append("ct_commodity = %s")
        params.append(COMMODITY_CODE.get(commodity, commodity))
    if source:
        conditions.append("ct_source = %s")
        params.append(SOURCE_CODE.get(source, source))
    if origin:
        conditions.append("origin = %s")
        params.append(origin)
    if status:
        conditions.append("status = %s")
        params.append(status)
    if date_from:
        conditions.append("completed_date >= %s")
        params.append(date_from)
    if date_to:
        conditions.append("completed_date <= %s")
        params.append(date_to)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    return where, params


async def _facets(where: str, params: list[Any]) -> Facets:
    async def bucket(column: str) -> list[dict[str, Any]]:
        return await fetch_all(
            f"SELECT {column} AS value, COUNT(*) AS count FROM vw_colas {where} "
            f"GROUP BY {column} ORDER BY count DESC",
            params,
        )

    commodity_rows = await bucket("ct_commodity")
    source_rows = await bucket("ct_source")
    origin_rows = await bucket("origin")
    status_rows = await bucket("status")

    return Facets(
        commodity=[
            FacetBucket(value=commodity_label(r["value"]), count=r["count"])
            for r in commodity_rows
            if r["value"] is not None
        ],
        source=[
            FacetBucket(value=source_label(r["value"]), count=r["count"])
            for r in source_rows
            if r["value"] is not None
        ],
        origin=[
            FacetBucket(value=r["value"], count=r["count"])
            for r in origin_rows
            if r["value"]
        ],
        status=[
            FacetBucket(value=r["value"], count=r["count"])
            for r in status_rows
            if r["value"]
        ],
    )


@router.get("/colas", response_model=SearchResponse)
async def list_colas(
    q: str | None = Query(
        default=None,
        title="Keyword search",
        description=(
            "Free-text keyword search. The value is wrapped in wildcards (`%term%`) and "
            "matched case-insensitively (SQL `ILIKE`) against several columns of the "
            "`vw_colas` view at once: brand name, fanciful name, applicant name, "
            "class/type, origin, the numeric COLA/TTB id, and the serial number. A row is "
            "returned if the term appears in any of those fields. Leave empty to browse "
            "all records without keyword filtering."
        ),
        examples=["cabernet", "napa valley", "26J087"],
    ),
    ttb_id: str | None = Query(default=None, alias="ttbId"),
    brand: str | None = None,
    fanciful: str | None = None,
    commodity: str | None = None,
    source: str | None = None,
    origin: str | None = None,
    status: str | None = None,
    date_from: date | None = Query(default=None, alias="dateFrom"),
    date_to: date | None = Query(default=None, alias="dateTo"),
    sort: str = Query(
        default="relevance",
        title="Result ordering",
        description=(
            "Controls the `ORDER BY` applied to the matching rows. Accepted values:\n\n"
            "- `relevance` (default) — newest first by approval/completed date "
            "(`completed_date DESC`, nulls last). Currently an alias of `approvalDate`; "
            "reserved for future keyword-relevance ranking.\n"
            "- `approvalDate` — newest approved/completed COLAs first "
            "(`completed_date DESC`, nulls last).\n"
            "- `brand` — alphabetical by brand name (`brand_name ASC`, nulls last).\n\n"
            "Any unrecognized value falls back to `relevance`."
        ),
        examples=["relevance", "approvalDate", "brand"],
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100, alias="pageSize"),
    facets: bool = Query(
        default=True,
        title="Include facet aggregations",
        description=(
            "When `true`, the response includes a `facets` object with aggregated counts "
            "for the current result set (the same filters are applied). Each facet is a "
            "`GROUP BY ... COUNT(*)` roll-up over the matching rows, ordered by count "
            "descending, for four dimensions: commodity (wine/beer/distilled spirits), "
            "source (domestic/import), origin, and status. These power the sidebar filter "
            "counts in the UI. Set to `false` to skip the extra aggregation queries when "
            "you only need the paged `items` list (slightly faster)."
        ),
    ),
) -> SearchResponse:
    where, params = _build_filters(
        q, ttb_id, brand, fanciful, commodity, source, origin, status, date_from, date_to
    )
    order_by = SORTS.get(sort, SORTS["relevance"])
    offset = (page - 1) * page_size

    total_row = await fetch_one(
        f"SELECT COUNT(*) AS n FROM vw_colas {where}", params
    )
    total = int(total_row["n"]) if total_row else 0

    rows = await fetch_all(
        f"SELECT * FROM vw_colas {where} ORDER BY {order_by} LIMIT %s OFFSET %s",
        [*params, page_size, offset],
    )

    return SearchResponse(
        items=[summary_from_row(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
        facets=(await _facets(where, params)) if facets else None,
    )


@router.get("/colas/{cola_id}", response_model=ColaDetail)
async def get_cola(cola_id: int) -> ColaDetail:
    base = await fetch_one("SELECT * FROM vw_colas WHERE cola_id = %s", [cola_id])
    if base is None:
        raise HTTPException(status_code=404, detail="COLA not found")

    images = await fetch_all(
        "SELECT cola_id, file_name, img_type, width_px, height_px FROM cola_images "
        "WHERE cola_id = %s ORDER BY "
        "CASE upper(coalesce(img_type,'')) WHEN 'FRONT' THEN 0 WHEN 'BACK' THEN 1 "
        "WHEN 'NECK' THEN 2 ELSE 3 END, file_name",
        [cola_id],
    )
    items = await fetch_all(
        "SELECT i.cola_id, i.file_name, i.analysis_item_type, i.text, i.model_confidence, "
        "i.bounding_box, i.analysis_model, img.img_type "
        "FROM image_analysis_items i "
        "LEFT JOIN cola_images img ON img.cola_id = i.cola_id AND img.file_name = i.file_name "
        "WHERE i.cola_id = %s ORDER BY i.id",
        [cola_id],
    )
    varietal_rows = await fetch_all(
        "SELECT vartl_name FROM cola_grape_varietals WHERE cola_id = %s ORDER BY vartl_name",
        [cola_id],
    )
    varietals = [r["vartl_name"] for r in varietal_rows if r.get("vartl_name")]

    qual_rows = await fetch_all(
        "SELECT qualification_text FROM cola_qualifications "
        "WHERE cola_id = %s AND qualification_text IS NOT NULL",
        [cola_id],
    )
    qualifications = (
        " ".join(r["qualification_text"] for r in qual_rows) if qual_rows else None
    )

    return detail_from_rows(base, images, items, varietals, qualifications)
