"""COLA list/search and detail endpoints."""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..db import fetch_all, fetch_one
from ..mappers import (
    COMMODITY_CODE,
    DETAIL_COLUMNS,
    SOURCE_CODE,
    SUMMARY_COLUMNS,
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
    "applicant": "applicant_name ASC NULLS LAST",
}

# Columns scanned by the free-text `q` parameter.
KEYWORD_COLUMNS = (
    "brand_name",
    "fanciful_name",
    "applicant_name",
    "class_type",
    "origin",
    "cola_id::text",
    "serial_num",
    "permit_num",
    "primary_permit_id",
    "primary_permit_name",
    "primary_permit_city_addr",
    "primary_permit_state_addr",
    "submtr_frst_name",
    "submtr_last_name",
    "grape_varietal",
)

# Matches a permit id against the primary permit, the COLA's permit number, or
# any permit in the view's `permits` rollup.
_PERMIT_ID_MATCH = (
    "(permit_num ILIKE %s OR primary_permit_id ILIKE %s OR EXISTS ("
    "  SELECT 1 FROM jsonb_array_elements(coalesce(permits, '[]'::jsonb)) pe"
    "  WHERE pe->>'permit_id' ILIKE %s))"
)

# Matches a permit/business name against the primary permit or any permit.
_PERMIT_NAME_MATCH = (
    "(primary_permit_name ILIKE %s OR EXISTS ("
    "  SELECT 1 FROM jsonb_array_elements(coalesce(permits, '[]'::jsonb)) pe"
    "  WHERE pe->>'permit_name' ILIKE %s))"
)


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
    applicant: str | None = None,
    permit: str | None = None,
    permit_name: str | None = None,
    permit_state: str | None = None,
    permit_city: str | None = None,
    submitter: str | None = None,
    varietal: str | None = None,
    qualification: str | None = None,
    label_text: str | None = None,
) -> tuple[str, list[Any]]:
    conditions: list[str] = []
    params: list[Any] = []

    if q:
        like = f"%{q}%"
        conditions.append(
            "(" + " OR ".join(f"{c} ILIKE %s" for c in KEYWORD_COLUMNS) + ")"
        )
        params.extend([like] * len(KEYWORD_COLUMNS))
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
    if applicant:
        conditions.append("applicant_name ILIKE %s")
        params.append(f"%{applicant}%")
    if permit:
        conditions.append(_PERMIT_ID_MATCH)
        params.extend([f"%{permit}%"] * 3)
    if permit_name:
        conditions.append(_PERMIT_NAME_MATCH)
        params.extend([f"%{permit_name}%"] * 2)
    if permit_state:
        conditions.append("upper(primary_permit_state_addr) = upper(%s)")
        params.append(permit_state)
    if permit_city:
        conditions.append("primary_permit_city_addr ILIKE %s")
        params.append(f"%{permit_city}%")
    if submitter:
        conditions.append(
            "(btrim(coalesce(submtr_frst_name, '') || ' ' || coalesce(submtr_last_name, '')) "
            "ILIKE %s OR submitter_id ILIKE %s)"
        )
        params.extend([f"%{submitter}%", f"%{submitter}%"])
    if varietal:
        conditions.append("grape_varietal ILIKE %s")
        params.append(f"%{varietal}%")
    if qualification:
        conditions.append("parsed_qualifications ILIKE %s")
        params.append(f"%{qualification}%")
    if label_text:
        conditions.append("ocr_text ILIKE %s")
        params.append(f"%{label_text}%")
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
    permit_state_rows = await bucket("primary_permit_state_addr")

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
        permit_state=[
            FacetBucket(value=r["value"], count=r["count"])
            for r in permit_state_rows
            if r["value"] and r["value"].strip()
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
            "class/type, origin, the numeric COLA/TTB id, the serial number, the permit "
            "number and primary permit id/name/city/state, the submitter's first and "
            "last name, and the grape varietal list. A row is returned if the term "
            "appears in any of those fields. Text recognized on the label images is not "
            "scanned here — use `labelText` for that. Leave empty to browse all records "
            "without keyword filtering."
        ),
        examples=["cabernet", "napa valley", "26J087"],
    ),
    ttb_id: str | None = Query(default=None, alias="ttbId"),
    brand: str | None = None,
    fanciful: str | None = None,
    applicant: str | None = Query(
        default=None,
        description="Applicant/business name (primary permit name, falling back to the submitter).",
    ),
    permit: str | None = Query(
        default=None,
        description="Permit or plant number. Matches the COLA permit number, the primary permit id, or any associated permit.",
    ),
    permit_name: str | None = Query(
        default=None,
        alias="permitName",
        description="Permit holder name. Matches the primary permit or any associated permit.",
    ),
    permit_state: str | None = Query(
        default=None,
        alias="permitState",
        description="Two-letter state of the primary permit address (exact, case-insensitive).",
    ),
    permit_city: str | None = Query(
        default=None,
        alias="permitCity",
        description="City of the primary permit address (partial match).",
    ),
    submitter: str | None = Query(
        default=None,
        description="Submitter name or submitter id from the application.",
    ),
    varietal: str | None = Query(
        default=None,
        description="Grape varietal declared on the application (partial match).",
    ),
    qualification: str | None = Query(
        default=None,
        description="Text within the application's qualifications and qualification comments.",
    ),
    label_text: str | None = Query(
        default=None,
        alias="labelText",
        description=(
            "Text recognized by OCR on the label artwork. Scans the aggregated "
            "`ocr_text` column; slower than the other filters."
        ),
    ),
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
            "- `brand` — alphabetical by brand name (`brand_name ASC`, nulls last).\n"
            "- `applicant` — alphabetical by applicant/permit holder "
            "(`applicant_name ASC`, nulls last).\n\n"
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
            "descending, for five dimensions: commodity (wine/beer/distilled spirits), "
            "source (domestic/import), origin, status, and permit state. These power the "
            "sidebar filter counts in the UI. Set to `false` to skip the extra "
            "aggregation queries when you only need the paged `items` list (slightly faster)."
        ),
    ),
) -> SearchResponse:
    where, params = _build_filters(
        q,
        ttb_id,
        brand,
        fanciful,
        commodity,
        source,
        origin,
        status,
        date_from,
        date_to,
        applicant=applicant,
        permit=permit,
        permit_name=permit_name,
        permit_state=permit_state,
        permit_city=permit_city,
        submitter=submitter,
        varietal=varietal,
        qualification=qualification,
        label_text=label_text,
    )
    order_by = SORTS.get(sort, SORTS["relevance"])
    offset = (page - 1) * page_size

    total_row = await fetch_one(
        f"SELECT COUNT(*) AS n FROM vw_colas {where}", params
    )
    total = int(total_row["n"]) if total_row else 0

    rows = await fetch_all(
        f"SELECT {SUMMARY_COLUMNS} FROM vw_colas {where} "
        f"ORDER BY {order_by} LIMIT %s OFFSET %s",
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
    base = await fetch_one(
        f"SELECT {DETAIL_COLUMNS} FROM vw_colas WHERE cola_id = %s", [cola_id]
    )
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

    return detail_from_rows(base, images, items)
