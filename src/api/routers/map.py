"""Map viewport endpoints over the materialised geolocation surface.

``cola_map_search`` holds one row per COLA per geocoded location, so a COLA with
several permits appears once per premise. Every query here is bounded twice: by
the viewport, which the GiST index answers, and by a scan cap, so panning to a
world view cannot turn into a full-table aggregation inside the statement
timeout.

Heat mode aggregates onto a server-side grid rather than returning raw points:
at low zoom a viewport covers millions of rows, and the browser cannot render
them even if the wire could carry them.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import Response, StreamingResponse
from psycopg.errors import UndefinedTable

from ..blob import RangeNotSatisfiable, stream_blob_range
from ..config import get_settings
from ..db import fetch_all, fetch_one
from ..mappers import (
    COMMODITY_CODE,
    MAP_TABLE,
    SEARCH_TABLE,
    SOURCE_CODE,
    SUMMARY_COLUMN_LIST,
    commodity_label,
    image_url,
    select_columns,
    source_label,
    summary_from_row,
)
from ..models import (
    FacetBucket,
    MapAreaResponse,
    MapHeatBin,
    MapImagePoint,
    MapPointsResponse,
)
from ..ratelimit import SlidingWindowLimiter, client_key

logger = logging.getLogger(__name__)

router = APIRouter(tags=["map"])

# permit_premise is every permit on a COLA, primary_premise just the one it was
# filed under, product_origin the state or country centroid for its origin code.
ROLES = ("primary_premise", "permit_premise", "product_origin")
MODES = ("heat", "image")

# Bins are already an aggregate; past this many the map is a solid block and the
# payload is pointless. Ordered by count, so what is dropped is the sparse tail.
BIN_CAP = 5000
# Records listed alongside an area summary, per page.
AREA_PAGE_SIZE = 24

_limiter: SlidingWindowLimiter | None = None


def _map_limiter() -> SlidingWindowLimiter:
    global _limiter
    if _limiter is None:
        settings = get_settings()
        _limiter = SlidingWindowLimiter(
            settings.map_rate_limit, settings.map_rate_window_seconds
        )
    return _limiter


def reset_limiter() -> None:
    global _limiter
    _limiter = None


def _enforce_rate_limit(request: Request) -> None:
    settings = get_settings()
    retry_after = _map_limiter().check(
        client_key(request, settings.trust_forwarded_for)
    )
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many map requests. Wait a moment and try again.",
            headers={"Retry-After": str(int(retry_after) + 1)},
        )


def _cell_size(zoom: int) -> float:
    """Grid cell in degrees for a zoom level, at roughly 8 bins per tile.

    Halving with each zoom step keeps a bin the same size on screen however far
    in the user is, so the heat surface does not re-scale as they navigate.
    """
    z = min(max(zoom, 0), 16)
    return 360.0 / (2**z) / 8


def _wrap_longitude(value: float) -> float:
    """Fold a longitude into [-180, 180]; map panning runs past the edges."""
    return ((value + 180.0) % 360.0) - 180.0


def _bbox_condition(
    west: float, south: float, east: float, north: float
) -> tuple[str, list[Any]]:
    """Viewport predicate against the GiST-indexed geography column.

    A viewport straddling the antimeridian arrives with west greater than east
    and has to be tested as two envelopes; one envelope spanning the difference
    would select the whole rest of the world instead.
    """
    south = max(-90.0, min(90.0, south))
    north = max(-90.0, min(90.0, north))
    if north < south:
        south, north = north, south

    envelope = "location && ST_MakeEnvelope(%s, %s, %s, %s, 4326)::geography"
    if east - west >= 360.0:
        return envelope, [-180.0, south, 180.0, north]

    west, east = _wrap_longitude(west), _wrap_longitude(east)
    if west > east:
        return (
            f"({envelope} OR {envelope})",
            [west, south, 180.0, north, -180.0, south, east, north],
        )
    return envelope, [west, south, east, north]


def build_map_filters(
    west: float,
    south: float,
    east: float,
    north: float,
    role: str,
    commodity: str | None = None,
    source: str | None = None,
    origin: str | None = None,
    class_type: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[str, list[Any]]:
    """WHERE clause for a viewport query, and the parameters it binds."""
    bbox_sql, params = _bbox_condition(west, south, east, north)
    conditions = [bbox_sql, "location_role = %s"]
    params.append(role)

    if commodity:
        conditions.append("ct_commodity = %s")
        params.append(COMMODITY_CODE.get(commodity, commodity))
    if source:
        conditions.append("ct_source = %s")
        params.append(SOURCE_CODE.get(source, source))
    if origin:
        conditions.append("origin = %s")
        params.append(origin)
    if class_type:
        # As on the search endpoint: the UI sends the description, an API caller
        # may send the code.
        term = class_type.strip()
        conditions.append("(upper(class_type) = upper(%s) OR class_type_code = %s)")
        params.extend([term, term])
    if date_from:
        conditions.append("completed_date >= %s")
        params.append(date_from)
    if date_to:
        conditions.append("completed_date <= %s")
        params.append(date_to)

    return "WHERE " + " AND ".join(conditions), params


def _validate(role: str, mode: str | None = None) -> None:
    if role not in ROLES:
        raise HTTPException(
            status_code=400, detail=f"role must be one of {', '.join(ROLES)}"
        )
    if mode is not None and mode not in MODES:
        raise HTTPException(
            status_code=400, detail=f"mode must be one of {', '.join(MODES)}"
        )


def _unavailable(exc: Exception) -> HTTPException:
    """The map surface is built by a later pipeline stage than the search one."""
    logger.warning("map surface is not available", exc_info=exc)
    return HTTPException(
        status_code=503,
        detail="Map data has not been built for this environment yet.",
    )


async def _heat_bins(
    where: str, params: list[Any], cell: float, cap: int
) -> tuple[list[MapHeatBin], int, bool]:
    rows = await fetch_all(
        f"""--sql
        WITH m AS (
            SELECT latitude, longitude FROM {MAP_TABLE} {where} LIMIT %s
        ), g AS (
            SELECT floor(longitude / %s) AS gx, floor(latitude / %s) AS gy,
                   count(*) AS n
              FROM m GROUP BY 1, 2
        )
        SELECT gx, gy, n, (SELECT count(*) FROM m) AS scanned
          FROM g ORDER BY n DESC LIMIT %s
        """,
        [*params, cap + 1, cell, cell, BIN_CAP],
    )

    scanned = int(rows[0]["scanned"]) if rows else 0
    capped = scanned > cap
    bins = [
        MapHeatBin(
            # The grid index is the cell's lower corner; the point drawn is its
            # centre, so a bin does not visually sit south-west of its records.
            lng=round((float(r["gx"]) + 0.5) * cell, 6),
            lat=round((float(r["gy"]) + 0.5) * cell, 6),
            count=int(r["n"]),
        )
        for r in rows
    ]
    return bins, min(scanned, cap), capped


async def _image_points(
    where: str, params: list[Any], limit: int
) -> list[MapImagePoint]:
    rows = await fetch_all(
        f"""--sql
        WITH m AS (
            SELECT cola_id, latitude, longitude, ct_commodity, origin,
                   completed_date, best_image_file_name
              FROM {MAP_TABLE} {where}
             ORDER BY (best_image_file_name IS NULL), completed_date DESC NULLS LAST,
                      cola_id DESC
             LIMIT %s
        )
        SELECT m.*, s.brand_name
          FROM m LEFT JOIN {SEARCH_TABLE} s ON s.cola_id = m.cola_id
        """,
        [*params, limit],
    )

    points = []
    for row in rows:
        file_name = row.get("best_image_file_name")
        points.append(
            MapImagePoint(
                id=str(row["cola_id"]),
                lat=float(row["latitude"]),
                lng=float(row["longitude"]),
                brand=row.get("brand_name"),
                category=commodity_label(row.get("ct_commodity")),
                origin=row.get("origin"),
                approval_date=row.get("completed_date"),
                thumb_url=(
                    image_url(str(row["cola_id"]), file_name) if file_name else None
                ),
            )
        )
    return points


@router.get("/map/points", response_model=MapPointsResponse)
async def map_points(
    request: Request,
    west: Annotated[float, Query(description="Viewport west longitude.")],
    south: Annotated[float, Query(description="Viewport south latitude.")],
    east: Annotated[float, Query(description="Viewport east longitude.")],
    north: Annotated[float, Query(description="Viewport north latitude.")],
    zoom: Annotated[
        int,
        Query(
            ge=0,
            le=22,
            description=(
                "Map zoom level. Sets the heat grid cell size so a bin stays the "
                "same size on screen at any zoom. Ignored in image mode."
            ),
        ),
    ] = 4,
    mode: Annotated[
        str,
        Query(
            description=(
                "`heat` aggregates the viewport onto a grid and returns bins with "
                "counts. `image` returns individual COLAs with a label thumbnail, "
                "capped so the map stays readable."
            ),
        ),
    ] = "heat",
    role: Annotated[
        str,
        Query(
            description=(
                "Which location to map. `primary_premise` is the permit the COLA "
                "was filed under, `permit_premise` every permit on it, and "
                "`product_origin` the centroid of its origin state or country. "
                "Origins are centroids, not addresses: they cluster every COLA "
                "from a place onto one point by design."
            ),
        ),
    ] = "primary_premise",
    commodity: str | None = None,
    source: str | None = None,
    origin: str | None = None,
    class_type: Annotated[str | None, Query(alias="classType")] = None,
    date_from: Annotated[date | None, Query(alias="dateFrom")] = None,
    date_to: Annotated[date | None, Query(alias="dateTo")] = None,
) -> MapPointsResponse:
    _enforce_rate_limit(request)
    _validate(role, mode)

    settings = get_settings()
    where, params = build_map_filters(
        west, south, east, north, role, commodity, source, origin,
        class_type, date_from, date_to,
    )

    try:
        if mode == "image":
            points = await _image_points(where, params, settings.map_image_point_cap)
            return MapPointsResponse(
                mode=mode,
                role=role,
                points=points,
                total=len(points),
                total_is_capped=len(points) >= settings.map_image_point_cap,
            )

        bins, total, capped = await _heat_bins(
            where, params, _cell_size(zoom), settings.map_scan_cap
        )
    except UndefinedTable as exc:
        raise _unavailable(exc) from exc

    return MapPointsResponse(
        mode=mode, role=role, bins=bins, total=total, total_is_capped=capped
    )


@router.get("/map/area", response_model=MapAreaResponse)
async def map_area(
    request: Request,
    west: Annotated[float, Query(description="Selection west longitude.")],
    south: Annotated[float, Query(description="Selection south latitude.")],
    east: Annotated[float, Query(description="Selection east longitude.")],
    north: Annotated[float, Query(description="Selection north latitude.")],
    role: str = "primary_premise",
    commodity: str | None = None,
    source: str | None = None,
    origin: str | None = None,
    class_type: Annotated[str | None, Query(alias="classType")] = None,
    date_from: Annotated[date | None, Query(alias="dateFrom")] = None,
    date_to: Annotated[date | None, Query(alias="dateTo")] = None,
    page: Annotated[int, Query(ge=1, le=100)] = 1,
) -> MapAreaResponse:
    """Summarise one selected area of the map, and list the COLAs in it."""
    _enforce_rate_limit(request)
    _validate(role)

    settings = get_settings()
    cap = settings.map_scan_cap
    where, params = build_map_filters(
        west, south, east, north, role, commodity, source, origin,
        class_type, date_from, date_to,
    )

    # Same shape as the search facets: one materialised CTE, scanned once and
    # rolled up across every dimension.
    summary_sql = f"""--sql
    WITH m AS (
        SELECT ct_commodity, ct_source, origin, class_type
          FROM {MAP_TABLE} {where} LIMIT %s
    )
    SELECT 'commodity' AS dim, ct_commodity AS value, count(*) AS count FROM m GROUP BY 1, 2
    UNION ALL SELECT 'source', ct_source, count(*) FROM m GROUP BY 1, 2
    UNION ALL SELECT 'origin', origin, count(*) FROM m GROUP BY 1, 2
    UNION ALL SELECT 'classType', class_type, count(*) FROM m GROUP BY 1, 2
    """
    items_sql = f"""--sql
    WITH m AS (
        SELECT cola_id FROM {MAP_TABLE} {where}
         ORDER BY completed_date DESC NULLS LAST, cola_id DESC
         LIMIT %s OFFSET %s
    )
    SELECT {select_columns(SUMMARY_COLUMN_LIST, "s")}
      FROM m JOIN {SEARCH_TABLE} s ON s.cola_id = m.cola_id
     ORDER BY s.completed_date DESC NULLS LAST, s.cola_id DESC
    """
    count_sql = f"SELECT count(*) AS n FROM (SELECT 1 FROM {MAP_TABLE} {where} LIMIT %s) t"

    try:
        summary_rows, item_rows, total_row = await asyncio.gather(
            fetch_all(summary_sql, [*params, cap]),
            fetch_all(items_sql, [*params, AREA_PAGE_SIZE, (page - 1) * AREA_PAGE_SIZE]),
            fetch_one(count_sql, [*params, cap + 1]),
        )
    except UndefinedTable as exc:
        raise _unavailable(exc) from exc

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in summary_rows:
        grouped.setdefault(row["dim"], []).append(row)

    def buckets(dim: str, label=lambda v: v) -> list[FacetBucket]:
        rows = sorted(
            (r for r in grouped.get(dim, []) if r["value"]),
            key=lambda r: r["count"],
            reverse=True,
        )
        return [FacetBucket(value=label(r["value"]), count=r["count"]) for r in rows]

    raw_total = int(total_row["n"]) if total_row else 0
    capped = raw_total > cap

    return MapAreaResponse(
        total=cap if capped else raw_total,
        total_is_capped=capped,
        commodity=buckets("commodity", commodity_label),
        source=buckets("source", source_label),
        origin=buckets("origin"),
        class_type=buckets("classType"),
        items=[summary_from_row(r) for r in item_rows],
    )


@router.get("/map/basemap", include_in_schema=False)
async def basemap(request: Request):
    """Serve the PMTiles basemap archive, honouring byte ranges.

    PMTiles is read by the client as ranged requests into a single archive, so
    this has to answer 206s rather than stream the whole file. The archive lives
    in the same private container as the label images and is proxied for the
    same reason: nothing in storage is publicly reachable.
    """
    blob_name = get_settings().map_basemap_blob
    if not blob_name:
        raise HTTPException(status_code=404, detail="No basemap is configured")

    try:
        chunks, content_length, content_range, _size = await stream_blob_range(
            blob_name, request.headers.get("range")
        )
    except RangeNotSatisfiable as exc:
        return Response(
            status_code=416, headers={"Content-Range": f"bytes */{exc.size}"}
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Basemap backend unavailable") from exc

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
        # The archive is replaced wholesale by a new upload, never edited, so it
        # is safe to cache for a long time.
        "Cache-Control": "public, max-age=604800, immutable",
    }
    if content_range is not None:
        headers["Content-Range"] = content_range

    return StreamingResponse(
        chunks,
        status_code=206 if content_range is not None else 200,
        media_type="application/octet-stream",
        headers=headers,
    )


# MapLibre substitutes the fontstack it asks for into the glyph URL verbatim, so
# the value reaching this route is attacker-controlled in principle. Restricting
# it to the shape of a real fontstack keeps it from walking out of the prefix.
GLYPH_PATTERN = r"^[A-Za-z0-9 ,_-]{1,120}$"
RANGE_PATTERN = r"^\d{1,5}-\d{1,5}$"


@router.get("/map/glyphs/{fontstack}/{glyph_range}.pbf", include_in_schema=False)
async def basemap_glyphs(
    fontstack: Annotated[str, Path(pattern=GLYPH_PATTERN)],
    glyph_range: Annotated[str, Path(pattern=RANGE_PATTERN)],
):
    """Serve the basemap's label fonts out of the same private container.

    Protomaps' own font host would work, but pointing the map at a third-party
    origin for every label range is exactly the dependency the proxied basemap
    exists to avoid. If the fonts were never provisioned this 404s and MapLibre
    simply draws the map without labels.
    """
    prefix = get_settings().map_basemap_blob
    if not prefix:
        raise HTTPException(status_code=404, detail="No basemap is configured")

    blob_name = f"{prefix.rsplit('/', 1)[0]}/fonts/{fontstack}/{glyph_range}.pbf"
    try:
        chunks, content_length, _range, _size = await stream_blob_range(blob_name, None)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Glyph range unavailable") from exc

    return StreamingResponse(
        chunks,
        media_type="application/x-protobuf",
        headers={
            "Content-Length": str(content_length),
            "Cache-Control": "public, max-age=604800, immutable",
        },
    )
