"""COLA list/search and detail endpoints."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request
from psycopg.errors import QueryCanceled, UndefinedTable

from ..config import get_settings
from ..db import fetch_all, fetch_one
from ..mappers import (
    APPLICATION_TYPE_SEP,
    APPLICATION_TYPES,
    COMMODITY_CODE,
    DETAIL_COLUMN_LIST,
    DETAIL_JSON_COLUMN_LIST,
    DETAIL_TABLE,
    MAP_TABLE,
    SEARCH_TABLE,
    SOURCE_CODE,
    SUMMARY_COLUMN_LIST,
    commodity_label,
    detail_from_rows,
    image_display_order_sql,
    select_columns,
    source_label,
    summary_from_row,
    visual_interest_join_sql,
)
from ..models import ColaDetail, FacetBucket, Facets, SearchResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["colas"])

# Exact totals stop here; past the cap the response reports a floor instead.
COUNT_CAP = 10_000

# cola_id breaks ties so LIMIT/OFFSET paging stays stable, and lines the sort up
# with the composite indexes on cola_search. Qualified because a keyword search
# joins a second relation that also carries cola_id.
_ID = f"{SEARCH_TABLE}.cola_id"
SORTS = {
    "relevance": f"completed_date DESC NULLS LAST, {_ID} DESC",
    "approvalDate": f"completed_date DESC NULLS LAST, {_ID} DESC",
    "brand": f"brand_name ASC NULLS LAST, {_ID} ASC",
    "applicant": f"applicant_name ASC NULLS LAST, {_ID} ASC",
}

# Identifier columns the free-text box probes exactly, alongside the tsvector.
# cola_id is text and matched verbatim: ids carry A/B/C/D/$ suffixes, embedded
# spaces and leading zeros, so they cannot be normalised to a number.
_ID_COLUMNS = ("cola_id", "serial_num", "permit_num", "primary_permit_id")

# Aliases of the materialised id sets the list statements join onto cola_search.
KEYWORD_ALIAS = "kw"

# Table-qualified, since the joined relations also expose cola_id.
_SUMMARY_COLUMNS = select_columns(SUMMARY_COLUMN_LIST, SEARCH_TABLE)

# --- Keyword matching --------------------------------------------------------
# search_tsv holds the record fields at weights A-C and the label OCR at weight
# D, so one document covers both and a weight restriction separates them. The
# restriction can be written two ways, and which one is used is a deployment
# setting because it depends on which indexes exist:
#
# - ts_filter(search_tsv, weights) @@ query, against a GIN index on that same
#   expression. Index-exact: the candidate set is only the rows matching at
#   those weights and no row is fetched to recheck.
# - search_tsv @@ query-with-weight-labels, against the plain GIN on search_tsv.
#   GIN stores lexemes without weights, so it returns every row that has the
#   lexeme at any weight and the executor fetches each one to recheck. For a
#   term that is mostly label text ("cabernet sauvignon": 21k record hits, 96k
#   candidates) that is 4x the heap fetches plus a detoast of the OCR-sized
#   tsvector per row - 22 s cold where the record-only index took 1 s.
#
# websearch_to_tsquery has no weight syntax, so for the second form the tsquery
# is rendered to text, every quoted lexeme gets a weight suffix, and it is parsed
# back. Lexemes are single-quoted with '' as the escape.
_TSQUERY = "websearch_to_tsquery('english', %s)"
_RECORD_WEIGHTS = "ABC"
_LABEL_WEIGHTS = "D"


def _weighted_tsquery(weights: str) -> str:
    return (
        f"regexp_replace({_TSQUERY}::text, "
        f"'''((?:[^'']|'''')*)''', '''\\1'':{weights}', 'g')::tsquery"
    )


def ts_filter_sql(weights: str) -> str:
    """The expression the upstream weight indexes are defined on."""
    labels = ",".join(weights.lower())
    return f"ts_filter(search_tsv, '{{{labels}}}'::\"char\"[])"


def weighted_match(weights: str) -> str:
    """`search_tsv` restricted to `weights` matches the bound term (one %s)."""
    if get_settings().search_weight_indexes:
        return f"{ts_filter_sql(weights)} @@ {_TSQUERY}"
    return f"search_tsv @@ {_weighted_tsquery(weights)}"


def _with_id_columns(match: str) -> str:
    return f"({match}" + "".join(f" OR {c} = %s" for c in _ID_COLUMNS) + ")"


def term_match() -> str:
    """Record fields or label text, plus the identifier columns."""
    return _with_id_columns(f"search_tsv @@ {_TSQUERY}")


def record_match() -> str:
    """Record fields only. Under the relevance sort these rank ahead of
    label-only matches, so a page they fill on their own is the whole answer."""
    return _with_id_columns(weighted_match(_RECORD_WEIGHTS))


def _term_params(q: str) -> list[Any]:
    term = q.strip()
    return [term, *([_id_term(term)] * len(_ID_COLUMNS))]


# Ranks rows whose record fields match above those that only match on label OCR.
# Without it the date sort would bury an exact brand hit under every label that
# happens to print the word.
_Q_RANK = f"{KEYWORD_ALIAS}.rec DESC"

# An index walk has to pass over every matching row before the page, so its cost
# grows with the offset (page 20 of "vodka" measured 2.5 s against 35 ms for
# page 1). The materialised form costs the same at any depth and takes over.
_INDEX_WALK_MAX_OFFSET = 240


@dataclass(frozen=True)
class Source:
    """A set of cola_ids, materialised once and joined onto cola_search.

    The other filters go inside it, with the term. A CTE has no ORDER BY or
    LIMIT, so the planner has nothing to gain from walking a sort index and
    testing the term row by row - the plan that ran past 120 s on "vodka" AND
    commodity=wine when the same predicates sat in an ordered, limited query -
    and instead ANDs the term's GIN bitmap with the filter's index (72k term
    matches x 2M wine rows resolve to 248 heap fetches). MATERIALIZED keeps the
    outer ORDER BY/LIMIT from being folded back in.
    """

    alias: str
    body: str
    params: list[Any] = field(default_factory=list)


def _keyword_source(
    q: str,
    where: str = "",
    where_params: list[Any] | None = None,
    *,
    record_only: bool = False,
    ranked: bool = False,
) -> Source:
    where_params = where_params or []
    if record_only:
        return Source(
            KEYWORD_ALIAS,
            f"SELECT cola_id FROM {SEARCH_TABLE} {_and(where, record_match())}",
            [*_term_params(q), *where_params],
        )
    if ranked:
        # The flag is computed here, once per match, rather than re-tested in
        # ORDER BY for every row the outer query touches.
        return Source(
            KEYWORD_ALIAS,
            f"SELECT cola_id, ({weighted_match(_RECORD_WEIGHTS)}) AS rec "
            f"FROM {SEARCH_TABLE} {_and(where, term_match())}",
            [q.strip(), *_term_params(q), *where_params],
        )
    return Source(
        KEYWORD_ALIAS,
        f"SELECT cola_id FROM {SEARCH_TABLE} {_and(where, term_match())}",
        [*_term_params(q), *where_params],
    )


# Permit id resolves against the COLA permit number, the primary permit, or the
# GIN-indexed permits rollup. All three arms sit on cola_search so the OR is one
# BitmapOr, or a filter on the sort-index walk when the prefix is common: a
# BWN-CA prefix covers 218k rows, which the walk answers in milliseconds and a
# materialised union answered in 13.7 s. The rollup therefore stays on
# cola_search until an indexed narrow equivalent (e.g. permit_ids text[]) exists
# there; the detail-table copy is read for display only.
_PERMIT_ID_MATCH = (
    "(permit_num LIKE %s OR primary_permit_id LIKE %s"
    " OR permits @> jsonb_build_array(jsonb_build_object('permit_id', %s::text)))"
)

# One box for "who made this": the business name or any of its permit numbers.
# applicant_name is the permit/plant name, falling back to the submitter when no
# permit is on file, and carries a trigram index, so the name half stays cheap.
_BUSINESS_MATCH = f"(applicant_name ILIKE %s OR {_PERMIT_ID_MATCH})"


def compose(sources: list[Source]) -> tuple[str, str, list[Any]]:
    """(WITH clause, FROM clause, parameters) for a set of sources."""
    if not sources:
        return "", SEARCH_TABLE, []
    with_sql = "WITH " + ", ".join(f"{s.alias} AS MATERIALIZED ({s.body})" for s in sources)
    from_sql = SEARCH_TABLE + "".join(
        f" JOIN {s.alias} ON {s.alias}.cola_id = {_ID}" for s in sources
    )
    return with_sql, from_sql, [p for s in sources for p in s.params]


def _and(where: str, condition: str) -> str:
    """Prepend a condition to a WHERE clause built by _build_filters."""
    if not where:
        return f"WHERE {condition}"
    return f"WHERE {condition} AND {where.removeprefix('WHERE ')}"


def only_status_filtered(filters: dict[str, Any]) -> bool:
    """Whether the term predicate can safely sit in the WHERE with the filters.

    status is the one filter the UI always sends and its dominant value covers
    97% of rows, so a common term cannot be absent from it and an index walk
    with the term as a filter stays short. Anything else goes through a Source.
    """
    return all(not value for name, value in filters.items() if name != "status")


# Filters with no index behind them: each one is a parallel sequential scan of
# the whole table (12-45s measured), which the paged rows survive by walking the
# date index and stopping early, but a count or facet aggregate cannot. Unless
# one of _ANCHOR_FILTERS narrows the set first, the aggregate is skipped.
_UNINDEXED_FILTERS = ("qualification", "submitter")
# Filters that reach the matching rows through a selective index.
_ANCHOR_FILTERS = (
    "q",
    "ttb_id",
    "brand",
    "fanciful",
    "applicant",
    "business",
    "permit",
    "permit_name",
    "permit_city",
    "varietal",
    "label_text",
    "class_type",
)


def _prefix(term: str) -> str:
    """LIKE pattern for a prefix match, with wildcards in the term neutralised."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"{escaped}%"


def _id_term(value: str) -> str:
    # TTB identifiers are uppercase upstream, and varchar_pattern_ops compares
    # bytes, so fold the input rather than the indexed column.
    return value.strip().upper()


def aggregate_is_affordable(**filters: Any) -> bool:
    """Whether a count/facet pass over this filter set can use an index."""
    if not any(filters.get(name) for name in _UNINDEXED_FILTERS):
        return True
    return any((filters.get(name) or "").strip() for name in _ANCHOR_FILTERS)


def _build_filters(
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
    business: str | None = None,
    permit: str | None = None,
    permit_name: str | None = None,
    permit_state: str | None = None,
    permit_city: str | None = None,
    submitter: str | None = None,
    varietal: str | None = None,
    qualification: str | None = None,
    label_text: str | None = None,
    class_type: str | None = None,
    received_by: str | None = None,
    application_type: str | None = None,
) -> tuple[str, list[Any]]:
    """WHERE clause for every filter except `q`, which resolves through a Source."""
    conditions: list[str] = []
    params: list[Any] = []

    if ttb_id:
        term = _id_term(ttb_id)
        conditions.append(f"({_ID} = %s OR serial_num LIKE %s)")
        params.extend([term, _prefix(term)])
    if brand:
        conditions.append("brand_name ILIKE %s")
        params.append(f"%{brand}%")
    if fanciful:
        conditions.append("fanciful_name ILIKE %s")
        params.append(f"%{fanciful}%")
    if applicant:
        conditions.append("applicant_name ILIKE %s")
        params.append(f"%{applicant}%")
    if business:
        term = business.strip()
        conditions.append(_BUSINESS_MATCH)
        id_term = _id_term(term)
        params.extend(
            [f"%{term}%", _prefix(id_term), _prefix(id_term), id_term]
        )
    if permit:
        term = _id_term(permit)
        conditions.append(_PERMIT_ID_MATCH)
        params.extend([_prefix(term), _prefix(term), term])
    if permit_name:
        # primary_permit_name never diverges from applicant_name (verified across
        # all 4.39M rows) and has no index, so this resolves against the indexed
        # copy instead.
        conditions.append("applicant_name ILIKE %s")
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
        conditions.append(weighted_match(_LABEL_WEIGHTS))
        params.append(label_text.strip())
    if commodity:
        conditions.append("ct_commodity = %s")
        params.append(COMMODITY_CODE.get(commodity, commodity))
    if class_type:
        # The description is what the UI sends; the code is accepted so an API
        # caller can filter straight off classTypeCode.
        term = class_type.strip()
        conditions.append("(upper(class_type) = upper(%s) OR class_type_code = %s)")
        params.extend([term, term])
    if received_by:
        # Only the code is indexed, so a description is resolved to its code
        # through the reference table rather than compared on the row.
        term = received_by.strip()
        conditions.append(
            "received_code IN (SELECT received_code FROM ref_received_codes "
            "WHERE upper(description) = upper(%s) UNION SELECT upper(%s))"
        )
        params.extend([term, term])
    if application_type:
        # The column is the form's multi-select joined into one string, so the
        # match is on a split component: a distinctive-bottle application is
        # "CERTIFICATE OF LABEL APPROVAL | DISTINCTIVE LIQUOR BOTTLE APPROVAL".
        # Written as array containment so it can use the GIN index on the same
        # expression; a LIKE '%...%' could not.
        conditions.append("string_to_array(application_type, %s) @> ARRAY[upper(%s)]")
        params.extend([APPLICATION_TYPE_SEP, application_type.strip()])
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


def _order_by(sort: str, ranked: bool) -> str:
    """ORDER BY for the requested sort; `ranked` when the keyword join is present."""
    key = sort if sort in SORTS else "relevance"
    if key == "relevance" and ranked:
        return f"{_Q_RANK}, {SORTS[key]}"
    return SORTS[key]


async def _count_and_facets(
    sources: list[Source], where: str, where_params: list[Any], want_facets: bool
) -> tuple[int, Facets | None] | None:
    """Capped match count and, optionally, facet counts, from one pass.

    The filtered set is materialised once in a CTE bounded by COUNT_CAP (PG
    materialises multiply-referenced CTEs by default) and every aggregate reads
    that. A broad term such as "vodka" matches tens of thousands of rows, and the
    bitmap heap fetch for all of them costs far more than the statement timeout
    allows; past the cap both the total and the facet counts are a floor, which
    total_is_capped reports.

    Returns None when the statement ran out of its time budget. The paged rows
    are what the user is waiting on, so an aggregate that cannot finish in time
    degrades the response instead of failing it.
    """
    settings = get_settings()
    with_sql, from_sql, source_params = compose(sources)
    columns = "ct_commodity, ct_source, origin, status, primary_permit_state_addr"
    sql = f"""--sql
        {with_sql}{', ' if with_sql else 'WITH '}m AS (
          SELECT {columns} FROM {from_sql} {where} LIMIT %s
        )
        SELECT 'total' AS dim, NULL::text AS value, COUNT(*) AS count FROM m
        """
    if want_facets:
        sql += """--sql
        UNION ALL SELECT 'commodity', ct_commodity, COUNT(*) FROM m GROUP BY 1, 2
        UNION ALL SELECT 'source', ct_source, COUNT(*) FROM m GROUP BY 1, 2
        UNION ALL SELECT 'origin', origin, COUNT(*) FROM m GROUP BY 1, 2
        UNION ALL SELECT 'status', status, COUNT(*) FROM m GROUP BY 1, 2
        UNION ALL SELECT 'permitState', primary_permit_state_addr, COUNT(*) FROM m GROUP BY 1, 2
        """
    try:
        rows = await fetch_all(
            sql,
            [*source_params, *where_params, COUNT_CAP + 1],
            work_mem=settings.search_work_mem,
            statement_timeout_ms=settings.search_count_timeout_ms,
            prepare=False,
        )
    except QueryCanceled:
        logger.info("search aggregate exceeded its time budget", extra={"where": where})
        return None

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["dim"], []).append(row)
    total = int(grouped["total"][0]["count"]) if grouped.get("total") else 0
    if not want_facets:
        return total, None

    def bucket(dim: str) -> list[dict[str, Any]]:
        return sorted(grouped.get(dim, []), key=lambda r: r["count"], reverse=True)

    return total, Facets(
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


async def _no_aggregate() -> tuple[int, Facets | None] | None:
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
            "Text recognized by OCR on the label artwork is searched too, so a COLA "
            "matches when the term appears only on the label; under `sort=relevance` "
            "those rows sort below record-field matches. Use `labelText` to search "
            "the label artwork alone. "
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
        description=(
            "Applicant/business name (primary permit name, falling back to the "
            "submitter). Superseded by `business`, which also matches permit numbers."
        ),
    ),
    business: str | None = Query(
        default=None,
        description=(
            "Business or permit, in one field. Matches the applicant/permit holder "
            "name as a substring, and the same term as a permit or plant number "
            "(prefix match on the COLA permit number and primary permit, exact "
            "match against any associated permit). This is what the advanced search "
            "form sends; `applicant`, `permit` and `permitName` remain for callers "
            "that need one half on its own."
        ),
        examples=["Cedar Hollow", "BWN-CA-1234"],
    ),
    permit: str | None = Query(
        default=None,
        description="Permit or plant number. Matches the COLA permit number or primary permit id on prefix, or any associated permit exactly.",
    ),
    permit_name: str | None = Query(
        default=None,
        alias="permitName",
        description=(
            "Permit holder name of the primary permit (partial match). Resolves "
            "against `applicant_name`, which holds the same value; superseded by "
            "`business`."
        ),
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
            "and matched against the indexed OCR document for the COLA. Unlike `q`, "
            "which spans both, this narrows the result set to the label artwork alone."
        ),
    ),
    commodity: str | None = None,
    class_type: str | None = Query(
        default=None,
        alias="classType",
        description=(
            "Granular TTB class/type on the application, e.g. `TABLE RED WINE`. "
            "Matched case-insensitively against the class/type description, or "
            "exactly against `classTypeCode`. Use `commodity` for the coarse "
            "wine/malt beverage/distilled spirits grouping."
        ),
        examples=["TABLE RED WINE", "80"],
    ),
    received_by: str | None = Query(
        default=None,
        alias="receivedBy",
        description=(
            "How TTB received the application. Matched case-insensitively against "
            "the received description, or exactly against the received code "
            "(`ES`, `MAIL`, `OVR`)."
        ),
        examples=["Electronic submission (COLAs Online)", "ES"],
    ),
    application_type: str | None = Query(
        default=None,
        alias="applicationType",
        description=(
            "Which box the applicant checked in item 14, TYPE OF APPLICATION. The "
            "item is a multi-select, so a record matches if the given type is any "
            "one of the types on the application. Transcribed from the certificate "
            "rather than supplied by the TTB API, so records that have not been "
            "through the form-scrape pass carry no value and never match."
        ),
        examples=list(APPLICATION_TYPES),
    ),
    source: str | None = None,
    origin: str | None = None,
    status: str | None = None,
    date_from: Annotated[
        date | None,
        Query(
            alias="dateFrom",
            description=(
                "Approval/completed date lower bound (`YYYY-MM-DD`). Omit both "
                "`dateFrom` and `dateTo` to search the full history."
            ),
        ),
    ] = None,
    date_to: Annotated[date | None, Query(alias="dateTo")] = None,
    sort: str = Query(
        default="relevance",
        title="Result ordering",
        description=(
            "Controls the `ORDER BY` applied to the matching rows. Every ordering is "
            "tie-broken on `cola_id` so paging is stable. Accepted values:\n\n"
            "- `relevance` (default) — with a `q` term, rows matching the record "
            "fields sort ahead of rows that match only on label OCR; within each "
            "group, newest first by approval/completed date. Without `q` it is "
            "identical to `approvalDate`.\n"
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
    settings = get_settings()
    filters: dict[str, Any] = dict(
        ttb_id=ttb_id,
        brand=brand,
        fanciful=fanciful,
        commodity=commodity,
        source=source,
        origin=origin,
        status=status,
        date_from=date_from,
        date_to=date_to,
        applicant=applicant,
        business=business,
        permit=permit,
        permit_name=permit_name,
        permit_state=permit_state,
        permit_city=permit_city,
        submitter=submitter,
        varietal=varietal,
        qualification=qualification,
        label_text=label_text,
        class_type=class_type,
        received_by=received_by,
        application_type=application_type,
    )
    term = (q or "").strip()
    where, where_params = _build_filters(**filters)
    ranked = bool(term) and (sort not in SORTS or sort == "relevance")
    offset = (page - 1) * page_size

    def rows_sql(sources: list[Source], where_sql: str, ranked_source: bool) -> tuple[str, list[Any]]:
        # A keyword source already carries the filters, so the outer WHERE is
        # empty in that case; the tier-1 pass has no source and keeps them.
        with_sql, from_sql, source_params = compose(sources)
        outer_params = where_params if where_sql else []
        return (
            f"{with_sql} SELECT {_SUMMARY_COLUMNS} FROM {from_sql} {where_sql} "
            f"ORDER BY {_order_by(sort, ranked=ranked_source)} LIMIT %s OFFSET %s",
            [*source_params, *outer_params, page_size + 1, offset],
        )

    async def run(sql: str, params: list[Any]) -> list[dict[str, Any]]:
        return await fetch_all(sql, params, work_mem=settings.search_work_mem, prepare=False)

    async def fetch_page() -> list[dict[str, Any]]:
        # One row past the page tells whether there is a next page when the count
        # is unavailable, and whether a record-only pass filled the page. It is
        # never returned.
        if ranked:
            # Record matches rank ahead of label-only ones, so a page they fill
            # on their own is the answer and label text is never consulted.
            if only_status_filtered(filters) and offset <= _INDEX_WALK_MAX_OFFSET:
                # Plain predicate: the planner may walk the sort index and
                # filter, which for a common term beats fetching every match.
                sql, params = rows_sql([], _and(where, record_match()), False)
                params[:0] = _term_params(term)
            else:
                sql, params = rows_sql(
                    [_keyword_source(term, where, where_params, record_only=True)], "", False
                )
            rows = await run(sql, params)
            if len(rows) > page_size:
                return rows
        if term:
            return await run(
                *rows_sql([_keyword_source(term, where, where_params, ranked=ranked)], "", ranked)
            )
        return await run(*rows_sql([], where, False))

    affordable = aggregate_is_affordable(q=q, **filters)
    if term:
        aggregate_coro = _count_and_facets(
            [_keyword_source(term, where, where_params)], "", [], facets
        )
    else:
        aggregate_coro = _count_and_facets([], where, where_params, facets)
    rows, aggregate = await asyncio.gather(
        fetch_page(), aggregate_coro if affordable else _no_aggregate()
    )

    has_more = len(rows) > page_size
    rows = rows[:page_size]
    if aggregate is not None:
        raw_total, facet_data = aggregate
        capped = raw_total > COUNT_CAP
        total = COUNT_CAP if capped else raw_total
    else:
        # No count: report what this page proves. A full page plus one more row
        # means at least one further page exists, which is enough for the pager.
        facet_data = None
        total = offset + len(rows) + (1 if has_more else 0)
        capped = has_more

    # Read back by the analytics middleware; the response body is not inspected.
    request.state.analytics = {
        "result_total": total,
        "zero_results": total == 0,
        "total_is_capped": capped,
        "count_skipped": not affordable,
        "count_timed_out": affordable and aggregate is None,
    }

    return SearchResponse(
        items=[summary_from_row(r) for r in rows],
        total=total,
        total_is_capped=capped,
        page=page,
        page_size=page_size,
        facets=facet_data,
    )


@router.get("/colas/{cola_id}", response_model=ColaDetail)
async def get_cola(cola_id: str) -> ColaDetail:
    return await load_detail(cola_id)


async def load_detail(cola_id: str) -> ColaDetail:
    """Assemble a full ColaDetail, or raise 404. Shared with the form renderer."""
    base = await fetch_one(
        f"SELECT {select_columns(DETAIL_COLUMN_LIST, 's')}, "
        f"{select_columns(DETAIL_JSON_COLUMN_LIST, 'd')} "
        f"FROM {SEARCH_TABLE} s LEFT JOIN {DETAIL_TABLE} d ON d.cola_id = s.cola_id "
        "WHERE s.cola_id = %s",
        [cola_id],
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
    locations, geo_status = await _geocoding(cola_id)

    return detail_from_rows(base, images, items, locations, geo_status)


async def _geocoding(cola_id: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Geocoded points for a COLA, plus why there are none when there are none.

    Both halves are optional: geolocation is a later pipeline stage than search,
    so its tables may not exist in an environment yet, and the detail page is
    still worth rendering without them.
    """
    try:
        locations = await fetch_all(
            f"SELECT location_role, source_key, permit_id, permit_name, latitude, longitude, "
            f"geolocation_quality, geolocation_provider, geolocation_method "
            f"FROM {MAP_TABLE} WHERE cola_id = %s "
            "ORDER BY (location_role <> 'primary_premise'), location_role, source_key",
            [cola_id],
        )
        # An observation exists once the address was normalised; a selection
        # exists once a provider answered, whether or not it matched.
        status = await fetch_one(
            """--sql
            SELECT count(*) AS observed_count,
                   count(s.result_id) AS selected_count
              FROM geolocation_observation o
              LEFT JOIN geolocation_selection s
                     ON s.target_kind = o.target_kind
                    AND s.normalizer_version = o.normalizer_version
                    AND s.target_key = o.target_key
             WHERE o.cola_id = %s
            """,
            [cola_id],
        )
    except UndefinedTable:
        logger.warning("geolocation tables are not available", exc_info=True)
        return [], None
    return locations, status
