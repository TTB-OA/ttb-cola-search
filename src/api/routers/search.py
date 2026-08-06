"""Vector similarity search — upload-image search and per-COLA similar labels."""
from __future__ import annotations

import logging
import math
from typing import Annotated, Any, cast

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from psycopg.abc import QueryNoTemplate
from psycopg.sql import SQL, Literal

from ..config import get_settings
from ..db import fetch_one, get_pool
from ..embedding import get_embedder
from ..mappers import (
    COMMODITY_CODE,
    IMAGE_TYPE_RANK_SQL,
    SEARCH_TABLE,
    SUMMARY_COLUMN_LIST,
    select_columns,
    summary_from_row,
)
from ..models import ColaSummary, SearchResponse
from ..ratelimit import SlidingWindowLimiter, client_key
from ..vectors import to_pgvector

router = APIRouter(tags=["search"])

logger = logging.getLogger(__name__)

_limiter: SlidingWindowLimiter | None = None


def _image_search_limiter() -> SlidingWindowLimiter:
    global _limiter
    if _limiter is None:
        settings = get_settings()
        _limiter = SlidingWindowLimiter(
            settings.image_search_rate_limit,
            settings.image_search_rate_window_seconds,
        )
    return _limiter

# A COLA carries several images, and the commodity filter is applied after
# de-duplication, so the ANN scan has to return more candidates than requested.
_ANN_OVERFETCH = 6


async def _nearest_by_vector(
    vector_literal: str,
    limit: int,
    commodity_code: str | None,
    exclude_cola_id: int | None,
    permit_num: str | None = None,
    permit_mode: str | None = None,
) -> list[ColaSummary]:
    params: list[Any] = [vector_literal]
    filters = ["i.image_feature_vector IS NOT NULL"]
    if exclude_cola_id is not None:
        filters.append("i.cola_id <> %s")
        params.append(exclude_cola_id)
    # Same-member results are far too sparse to survive a global ANN scan, so the
    # candidate set is narrowed to the permit holder before ranking by distance.
    # The inverse case filters inside the scan too, otherwise same-member rows
    # consume the candidate budget and starve the result set.
    if permit_mode and permit_num:
        op = "IN" if permit_mode == "same" else "NOT IN"
        filters.append(
            f"i.cola_id {op} (SELECT cola_id FROM {SEARCH_TABLE} WHERE permit_num = %s)"
        )
        params.append(permit_num)
    inner_where = " AND ".join(filters)

    candidates = limit * _ANN_OVERFETCH
    # The ORDER BY must be the bare distance operator (not an alias) for the
    # HNSW index to serve it; the literal is therefore bound twice.
    params.extend([vector_literal, candidates])

    query = (
        f"""--sql
        WITH knn AS (
          SELECT i.cola_id, (i.image_feature_vector <=> %s::vector) AS dist
          FROM cola_images i
          WHERE {inner_where}
          ORDER BY i.image_feature_vector <=> %s::vector
          LIMIT %s
        ), best AS (
          SELECT DISTINCT ON (cola_id) cola_id, dist FROM knn ORDER BY cola_id, dist
        )
        SELECT {select_columns(SUMMARY_COLUMN_LIST, 'v')}, b.dist
        FROM best b JOIN {SEARCH_TABLE} v ON v.cola_id = b.cola_id
        """
    )
    outer: list[str] = []
    if commodity_code:
        outer.append("v.ct_commodity = %s")
        params.append(commodity_code)
    if outer:
        query += " WHERE " + " AND ".join(outer)
    query += " ORDER BY b.dist LIMIT %s"
    params.append(limit)

    # ef_search has to exceed the candidate LIMIT or HNSW recall collapses.
    ef_search = max(64, candidates)
    async with get_pool().connection() as conn, conn.transaction(), conn.cursor() as cur:
        await cur.execute(SQL("SET LOCAL hnsw.ef_search TO {}").format(Literal(ef_search)))
        await cur.execute(cast(QueryNoTemplate, query), params)
        rows = cast(list[dict[str, Any]], await cur.fetchall())

    return [summary_from_row(r, score=round(1.0 - float(r["dist"]), 4)) for r in rows]


@router.post("/search/image", response_model=SearchResponse)
async def search_by_image(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    commodity: str | None = Form(default=None),
    limit: int = Form(default=48, ge=1, le=48),
) -> SearchResponse:
    settings = get_settings()

    # Checked before the body is read, so a flood costs neither memory nor an
    # embedding call.
    retry_after = _image_search_limiter().check(
        client_key(request, settings.trust_forwarded_for)
    )
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many image searches. Please wait a moment and try again.",
            headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
        )

    data = await file.read(settings.max_upload_bytes + 1)
    if not data:
        raise HTTPException(status_code=400, detail="Empty image upload")
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="Image exceeds the maximum upload size")

    try:
        embedder = get_embedder()
        vector = await embedder.embed_image(data, file.content_type or "image/jpeg")
    except Exception:
        logger.exception("Image embedding failed")
        raise HTTPException(status_code=503, detail="Embedding unavailable") from None

    if len(vector) != settings.embedding_dim:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Embedding dimension {len(vector)} does not match configured "
                f"column dimension {settings.embedding_dim}"
            ),
        )

    commodity_code = COMMODITY_CODE.get(commodity) if commodity else None
    items = await _nearest_by_vector(
        to_pgvector(vector), limit=limit, commodity_code=commodity_code, exclude_cola_id=None
    )
    return SearchResponse(items=items, total=len(items), page=1, page_size=limit)


@router.get("/colas/{cola_id}/similar", response_model=list[ColaSummary])
async def similar_colas(
    cola_id: int,
    limit: int = Query(default=12, ge=1, le=48),
    scope: str = Query(
        default="all",
        pattern="^(all|member|others)$",
        description=(
            "Restrict visually similar labels by industry member: 'member' keeps only "
            "COLAs sharing this permit number, 'others' excludes them, 'all' ignores the permit."
        ),
    ),
) -> list[ColaSummary]:
    seed = await fetch_one(
        "SELECT image_feature_vector::text AS vec FROM cola_images "
        "WHERE cola_id = %s AND image_feature_vector IS NOT NULL "
        f"ORDER BY {IMAGE_TYPE_RANK_SQL}, file_name LIMIT 1",
        [cola_id],
    )
    if seed is None or not seed.get("vec"):
        return []

    permit_num: str | None = None
    permit_mode: str | None = None
    if scope != "all":
        # permit_num is populated for every record, unlike primary_permit_id.
        row = await fetch_one(
            f"SELECT permit_num FROM {SEARCH_TABLE} WHERE cola_id = %s", [cola_id]
        )
        permit_num = (row or {}).get("permit_num")
        if not permit_num:
            return []
        permit_mode = "same" if scope == "member" else "other"

    return await _nearest_by_vector(
        seed["vec"],
        limit=limit,
        commodity_code=None,
        exclude_cola_id=cola_id,
        permit_num=permit_num,
        permit_mode=permit_mode,
    )
