"""Vector similarity search — upload-image search and per-COLA similar labels."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from ..config import get_settings
from ..db import fetch_all, fetch_one
from ..embedding import get_embedder
from ..mappers import COMMODITY_CODE, SUMMARY_COLUMN_LIST, select_columns, summary_from_row
from ..models import ColaSummary, SearchResponse
from ..vectors import to_pgvector

router = APIRouter(tags=["search"])


async def _nearest_by_vector(
    vector_literal: str,
    limit: int,
    commodity_code: str | None,
    exclude_cola_id: int | None,
) -> list[ColaSummary]:
    params: list[Any] = [vector_literal]
    filters = ["i.image_feature_vector IS NOT NULL"]
    if exclude_cola_id is not None:
        filters.append("i.cola_id <> %s")
        params.append(exclude_cola_id)
    inner_where = " AND ".join(filters)

    outer_conditions: list[str] = []
    if commodity_code:
        outer_conditions.append("v.ct_commodity = %s")

    # Best (smallest) distance per cola, then join back to the view.
    query = (
        f"SELECT {select_columns(SUMMARY_COLUMN_LIST, 'v')}, d.dist FROM ("
        "  SELECT DISTINCT ON (i.cola_id) i.cola_id, "
        "         (i.image_feature_vector <=> %s::vector) AS dist "
        f"  FROM cola_images i WHERE {inner_where} "
        "  ORDER BY i.cola_id, dist"
        ") d JOIN vw_colas v ON v.cola_id = d.cola_id "
    )
    if outer_conditions:
        query += "WHERE " + " AND ".join(outer_conditions) + " "
    query += "ORDER BY d.dist LIMIT %s"

    if commodity_code:
        params.append(commodity_code)
    params.append(limit)

    rows = await fetch_all(query, params)
    return [summary_from_row(r, score=round(1.0 - float(r["dist"]), 4)) for r in rows]


@router.post("/search/image", response_model=SearchResponse)
async def search_by_image(
    file: UploadFile = File(...),
    commodity: str | None = Form(default=None),
    limit: int = Form(default=48),
) -> SearchResponse:
    settings = get_settings()
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty image upload")

    try:
        embedder = get_embedder()
        vector = await embedder.embed_image(data, file.content_type or "image/jpeg")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Embedding unavailable: {exc}") from exc

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
) -> list[ColaSummary]:
    seed = await fetch_one(
        "SELECT image_feature_vector::text AS vec FROM cola_images "
        "WHERE cola_id = %s AND image_feature_vector IS NOT NULL "
        "ORDER BY CASE upper(coalesce(img_type,'')) WHEN 'FRONT' THEN 0 ELSE 1 END LIMIT 1",
        [cola_id],
    )
    if seed is None or not seed.get("vec"):
        return []
    return await _nearest_by_vector(
        seed["vec"], limit=limit, commodity_code=None, exclude_cola_id=cola_id
    )
