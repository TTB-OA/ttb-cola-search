"""COLA list/search and detail endpoints."""
from __future__ import annotations

import asyncio
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request

from ..db import fetch_all, fetch_one
from ..mappers import (
    COMMODITY_CODE,
    DETAIL_COLUMNS,
    OCR_TABLE,
    SEARCH_TABLE,
    SOURCE_CODE,
    SUMMARY_COLUMNS,
    commodity_label,
    detail_from_rows,
    image_display_order_sql,
    source_label,
    summary_from_row,
    visual_interest_join_sql,
)
from ..models import ColaDetail, FacetBucket, Facets, SearchResponse

router = APIRouter(tags=["colas"])

# Exact totals stop here; past the cap the response reports a floor instead.
COUNT_CAP = 10_000

# cola_id breaks ties so LIMIT/OFFSET paging stays stable, and lines the sort up
# with the composite indexes on cola_search.
SORTS = {
    "relevance": "completed_date DESC NULLS LAST, cola_id DESC",
    "approvalDate": "completed_date DESC NULLS LAST, cola_id DESC",
    "brand": "brand_name ASC NULLS LAST, cola_id ASC",
    "applicant": "applicant_name ASC NULLS LAST, cola_id ASC",
}

# Identifier columns the free-text box probes exactly, alongside the tsvector.
_ID_COLUMNS = ("serial_num", "permit_num", "primary_permit_id")

# Permit id resolves against the COLA permit number, the primary permit, or the
# GIN-indexed permits rollup.
_PERMIT_ID_MATCH = (
    "(permit_num LIKE %s OR primary_permit_id LIKE %s"
    " OR permits @> jsonb_build_array(jsonb_build_object('permit_id', %s::text)))"
)


def _prefix(term: str) -> str:
    """LIKE pattern for a prefix match, with wildcards in the term neutralised."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}%"


def _id_term(value: str) -> str:
    # TTB identifiers are uppercase upstream, and varchar_pattern_ops compares
    # bytes, so fold the input rather than the indexed column.
    return value.strip().upper()


def _default_date_from(today: date | None = None) -> date:
    d = today or date.today()
    return date(d.year - 2, 1, 1)


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
        term = q.strip()
        clause = ["search_tsv @@ websearch_to_tsquery('english', %s)"]
        params.append(term)
        clause.extend(f"{c} = %s" for c in _ID_COLUMNS)
        params.extend([_id_term(term)] * len(_ID_COLUMNS))
        if term.isdigit():
            clause.append("cola_id = %s")
            params.append(int(term))
        conditions.append("(" + " OR ".join(clause) + ")")
    if ttb_id:
        term = _id_term(ttb_id)
        if term.isdigit():
            conditions.append("(cola_id = %s OR serial_num LIKE %s)")
            params.extend([int(term), _prefix(term)])
        else:
            conditions.append("serial_num LIKE %s")
            params.append(_prefix(term))
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
        term = _id_term(permit)
        conditions.append(_PERMIT_ID_MATCH)
        params.extend([_prefix(term), _prefix(term), term])
    if permit_name:
        conditions.append("primary_permit_name ILIKE %s")
        params.append(f"%{permit_name}%")
    if permit_state:
        conditions.append("upper(primary_permit_state_addr) = upper(%s)")
        params.append(permit_state)
    if permit_city:
        conditions.append("primary_permit_city_addr ILIKE %s")
        params.append(f"%{permit_city}%")
    if submitter:
        conditions.append(
            "(btrim(coalesce(submtr_frst_name, '') || ' ' || coalesce(submtr_last_name, '')) "
            "ILIKE %s OR submitter_id LIKE %s)"
        )
        params.extend([f"%{submitter}%", _prefix(_id_term(submitter))])
    if varietal:
        conditions.append("grape_varietal ILIKE %s")
        params.append(f"%{varietal}%")
    if qualification:
        conditions.append("parsed_qualifications ILIKE %s")
        params.append(f"%{qualification}%")
    if label_text:
        conditions.append(
            f"EXISTS (SELECT 1 FROM {OCR_TABLE} o WHERE o.cola_id = {SEARCH_TABLE}.cola_id "
            "AND o.ocr_tsv @@ websearch_to_tsquery('english', %s))"
        )
        params.append(label_text.strip())
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
    # One materialised CTE (PG materialises multiply-referenced CTEs by default)
    # so the filtered set is scanned once instead of once per dimension.
    #
    # The CTE is bounded by the same COUNT_CAP as the total. A broad term such as
    # "vodka" matches tens of thousands of rows, and the bitmap heap fetch for all
    # of them costs far more than the statement timeout allows. Capping the scan
    # keeps the aggregation bounded; past the cap the counts are a floor, which
    # total_is_capped already reports for the same result set.
    rows = await fetch_all(
        f"""--sql
        WITH m AS (
          SELECT ct_commodity, ct_source, origin, status, primary_permit_state_addr
          FROM {SEARCH_TABLE} {where} LIMIT %s
        )
        SELECT 'commodity' AS dim, ct_commodity AS value, COUNT(*) AS count FROM m GROUP BY 1, 2
        UNION ALL SELECT 'source', ct_source, COUNT(*) FROM m GROUP BY 1, 2
        UNION ALL SELECT 'origin', origin, COUNT(*) FROM m GROUP BY 1, 2
        UNION ALL SELECT 'status', status, COUNT(*) FROM m GROUP BY 1, 2
        UNION ALL SELECT 'permitState', primary_permit_state_addr, COUNT(*) FROM m GROUP BY 1, 2
        """,
        [*params, COUNT_CAP],
    )

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["dim"], []).append(row)

    def bucket(dim: str) -> list[dict[str, Any]]:
        return sorted(grouped.get(dim, []), key=lambda r: r["count"], reverse=True)

    return Facets(
        commodity=[
            FacetBucket(value=commodity_label(r["value"]), count=r["count"])
            for r in bucket("commodity")
            if r["value"] is not None
        ],
        source=[
            FacetBucket(value=source_label(r["value"]), count=r["count"])
            for r in bucket("source")
            if r["value"] is not None
        ],
        origin=[
            FacetBucket(value=r["value"], count=r["count"])
            for r in bucket("origin")
            if r["value"]
        ],
        status=[
            FacetBucket(value=r["value"], count=r["count"])
            for r in bucket("status")
            if r["value"]
        ],
        permit_state=[
            FacetBucket(value=r["value"], count=r["count"])
            for r in bucket("permitState")
            if r["value"] and r["value"].strip()
        ],
    )


async def _no_facets() -> Facets | None:
    return None


@router.get("/colas", response_model=SearchResponse)
async def list_colas(
    request: Request,
    q: str | None = Query(
        default=None,
        title="Keyword search",
        description=(
            "Free-text keyword search. The term is parsed as a web-style query "
            "(`websearch_to_tsquery`) and matched against the indexed `search_tsv` "
            "document, which is weighted brand/fanciful name first, then "
            "applicant/permit holder, then the remaining descriptive fields. Quoted "
            "phrases, `or`, and leading `-` for exclusion are supported. The term is "
            "also compared exactly against the serial number, permit number and "
            "primary permit id, and against the numeric COLA id when it is all digits. "
            "Text recognized on the label images is not scanned here \u2014 use `labelText`. "
            "Leave empty to browse all records without keyword filtering."
        ),
        examples=["cabernet", '"napa valley"', "26J087"],
    ),
    ttb_id: str | None = Query(
        default=None,
        alias="ttbId",
        description="TTB/COLA id or serial number. Serial numbers match on prefix.",
    ),
    brand: str | None = None,
    fanciful: str | None = None,
    applicant: str | None = Query(
        default=None,
        description="Applicant/business name (primary permit name, falling back to the submitter).",
    ),
    permit: str | None = Query(
        default=None,
        description="Permit or plant number. Matches the COLA permit number or primary permit id on prefix, or any associated permit exactly.",
    ),
    permit_name: str | None = Query(
        default=None,
        alias="permitName",
        description="Permit holder name of the primary permit (partial match).",
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
            "Text recognized by OCR on the label artwork. Parsed as a web-style query "
            "and matched against the indexed OCR document for the COLA."
        ),
    ),
    commodity: str | None = None,
    source: str | None = None,
    origin: str | None = None,
    status: str | None = None,
    date_from: Annotated[
        date | None,
        Query(
            alias="dateFrom",
            description=(
                "Approval/completed date lower bound (`YYYY-MM-DD`). When both "
                "`dateFrom` and `dateTo` are omitted, searches default to Jan 1 of "
                "the year two years before the current year (last three calendar years), "
                "unless `allDates` is set."
            ),
        ),
    ] = None,
    date_to: Annotated[date | None, Query(alias="dateTo")] = None,
    all_dates: Annotated[
        bool,
        Query(
            alias="allDates",
            description=(
                "Search the full history instead of the default three-calendar-year "
                "window. Ignored when `dateFrom` or `dateTo` is supplied."
            ),
        ),
    ] = False,
    sort: str = Query(
        default="relevance",
        title="Result ordering",
        description=(
            "Controls the `ORDER BY` applied to the matching rows. Every ordering is "
            "tie-broken on `cola_id` so paging is stable. Accepted values:\n\n"
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
    page: int = Query(
        default=1,
        ge=1,
        le=500,
        description="1-based page number. Deep paging is capped; narrow the filters instead.",
    ),
    page_size: int = Query(default=24, ge=1, le=100, alias="pageSize"),
    facets: bool = Query(
        default=True,
        title="Include facet aggregations",
        description=(
            "When `true`, the response includes a `facets` object with aggregated counts "
            "for the current result set (the same filters are applied). A single "
            "`GROUP BY ... COUNT(*)` pass rolls up five dimensions: commodity "
            "(wine/beer/distilled spirits), source (domestic/import), origin, status, "
            "and permit state. These power the sidebar filter counts in the UI. Set to "
            "`false` to skip the aggregation when you only need the paged `items` list."
        ),
    ),
) -> SearchResponse:
    effective_date_from = date_from
    if date_from is None and date_to is None and not all_dates:
        effective_date_from = _default_date_from()

    where, params = _build_filters(
        q,
        ttb_id,
        brand,
        fanciful,
        commodity,
        source,
        origin,
        status,
        effective_date_from,
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

    # The count is bounded so a broad filter cannot force a full scan; anything
    # past the cap is reported as a floor via total_is_capped.
    count_sql = (
        f"SELECT COUNT(*) AS n FROM (SELECT 1 FROM {SEARCH_TABLE} {where} LIMIT %s) t"
    )
    rows_sql = (
        f"SELECT {SUMMARY_COLUMNS} FROM {SEARCH_TABLE} {where} "
        f"ORDER BY {order_by} LIMIT %s OFFSET %s"
    )

    total_row, rows, facet_data = await asyncio.gather(
        fetch_one(count_sql, [*params, COUNT_CAP + 1]),
        fetch_all(rows_sql, [*params, page_size, offset]),
        _facets(where, params) if facets else _no_facets(),
    )

    raw_total = int(total_row["n"]) if total_row else 0
    capped = raw_total > COUNT_CAP

    # Read back by the analytics middleware; the response body is not inspected.
    request.state.analytics = {
        "result_total": COUNT_CAP if capped else raw_total,
        "zero_results": raw_total == 0,
        "total_is_capped": capped,
    }

    return SearchResponse(
        items=[summary_from_row(r) for r in rows],
        total=COUNT_CAP if capped else raw_total,
        total_is_capped=capped,
        page=page,
        page_size=page_size,
        facets=facet_data,
    )


@router.get("/colas/{cola_id}", response_model=ColaDetail)
async def get_cola(cola_id: int) -> ColaDetail:
    base = await fetch_one(
        f"SELECT {DETAIL_COLUMNS} FROM {SEARCH_TABLE} WHERE cola_id = %s", [cola_id]
    )
    if base is None:
        raise HTTPException(status_code=404, detail="COLA not found")

    images = await fetch_all(
        "SELECT ci.cola_id, ci.file_name, ci.img_type, ci.width_px, ci.height_px, "
        "vi.visual_interest_score, vi.visual_interest_rank "
        "FROM cola_images ci "
        f"{visual_interest_join_sql('ci')} "
        "WHERE ci.cola_id = %s "
        f"ORDER BY {image_display_order_sql('ci')}",
        [cola_id],
    )
    items = await fetch_all(
        "SELECT i.cola_id, i.file_name, i.analysis_item_type, i.text, i.model_confidence, "
        "i.bounding_box, i.analysis_model, img.img_type, img.width_px, img.height_px "
        "FROM image_analysis_items i "
        "LEFT JOIN cola_images img ON img.cola_id = i.cola_id AND img.file_name = i.file_name "
        "WHERE i.cola_id = %s ORDER BY i.id",
        [cola_id],
    )

    return detail_from_rows(base, images, items)
