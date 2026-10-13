"""Map viewport endpoints over the materialised geolocation surface.

``cola_map_search`` holds one row per COLA per geocoded location, so a COLA with
several permits appears once per premise. Every query here is bounded twice: by
the viewport, which the GiST index answers, and by a scan cap, so panning to a
world view cannot turn into a full-table aggregation inside the statement
timeout.

Heat mode aggregates onto a server-side grid rather than returning raw points:
at low zoom a viewport covers millions of rows, and the browser cannot render
them even if the wire could carry them. It reads from the covering btree
``cola_map_search_heat_idx`` as an index-only scan where that exists; the
GiST-indexed geography column serves image and area mode, which fetch heap
rows anyway.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import Counter, OrderedDict, defaultdict
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
    MAP_HEAT_INDEX,
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
    FacetGroup,
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
# A wide desktop viewport is ~14 tiles, so this has to clear 14k to avoid
# punching holes in the sparse areas the grid is finest for.
BIN_CAP = 20000
# Records listed alongside an area summary, per page.
AREA_PAGE_SIZE = 24
# At or below this zoom a viewport is continental and reads most of a role's
# rows anyway, so the heat grid is built once for the whole world, cached, and
# clipped per viewport. Each screen size and pan would otherwise be its own
# cold 12-15 s scan, and the default national view routinely hit the timeout.
WORLD_GRID_MAX_ZOOM = 5
# The order the startup warm-up builds grids in: the page opens at zoom 3.
WARM_ZOOMS = (3, 4, 5, 2, 1, 0)

# Both endpoints filter the same surface, so the vocabulary and the wording are
# written once. The enums are advertised to OpenAPI rather than enforced by the
# type, so an unknown value still comes back as a 400 with an explanation
# instead of a 422 validation dump.
RoleParam = Annotated[
    str,
    Query(
        description=(
            "Which location to map. `primary_premise` is the premise of the permit "
            "the COLA was filed under, `permit_premise` the premise of every permit "
            "on it, and `product_origin` the centroid of its origin state or "
            "country. Origins are centroids, not addresses: they cluster every COLA "
            "from a place onto one point by design."
        ),
        json_schema_extra={"enum": list(ROLES)},
    ),
]
CommodityParam = Annotated[
    str | None,
    Query(
        description=(
            "Coarse product category. The underlying codes (`wine`, `beer`, "
            "`distilled_spirits`, `unknown`) are accepted too."
        ),
        json_schema_extra={"enum": list(COMMODITY_CODE)},
    ),
]
SourceParam = Annotated[
    str | None,
    Query(
        description=(
            "Whether the product is domestic or imported. The codes `domestic` and "
            "`import` are accepted too."
        ),
        json_schema_extra={"enum": list(SOURCE_CODE)},
    ),
]
OriginParam = Annotated[
    str | None,
    Query(
        description=(
            "Origin as TTB records it — a state for domestic COLAs, a country for "
            "imported ones. Exact match; `/reference` lists the values in use."
        ),
        examples=["California", "France"],
    ),
]
ClassTypeParam = Annotated[
    str | None,
    Query(
        alias="classType",
        description=(
            "Granular TTB class/type. Matched case-insensitively against the "
            "description, or exactly against the class/type code. Use `commodity` "
            "for the coarse grouping."
        ),
        examples=["TABLE RED WINE"],
    ),
]
DateFromParam = Annotated[
    date | None,
    Query(
        alias="dateFrom",
        description="Approval/completed date lower bound (`YYYY-MM-DD`).",
    ),
]
DateToParam = Annotated[
    date | None,
    Query(
        alias="dateTo",
        description="Approval/completed date upper bound (`YYYY-MM-DD`).",
    ),
]
VarietalParam = Annotated[
    str | None,
    Query(
        description=(
            "Grape varietal, matched as a substring because a COLA's varietal value "
            "is a joined list. Rejected with 400 where the map surface carries no "
            "varietal column; `/map/points` reports that as `varietalAvailable`."
        ),
        examples=["Cabernet Sauvignon"],
    ),
]

_limiter: SlidingWindowLimiter | None = None

# Varietal reached cola_map_search after the rest of the map did, so the column
# may not be there. Probed once rather than assumed, because the alternative is
# either a 500 on a filter the UI offered or silently unfiltered results.
_has_varietal: bool | None = None

# Heat mode reads three narrow columns off a 6.5 GB heap. A national viewport
# matches a quarter of the table, so the planner rightly refuses the GiST and
# sequentially scans the whole heap: 17-22 s, past the statement timeout. The
# covering btree (location_role, latitude, longitude) INCLUDE (filter columns)
# lets the same aggregate run as an index-only scan that never touches the
# heap, but only if the predicate stays off the geography column. Probed once
# so an environment without the index keeps the GiST path.
_has_heat_index: bool | None = None

# (zoom, role, filters) -> (built at, [(gx, gy, n), ...]) for the world grids.
GridKey = tuple[int, str, tuple[tuple[str, str], ...]]
GridCells = list[tuple[int, int, int]]
_grid_cache: OrderedDict[GridKey, tuple[float, GridCells]] = OrderedDict()
# One build per key at a time; concurrent viewports wait on the same task.
_grid_builds: dict[GridKey, asyncio.Task[GridCells]] = {}


async def varietal_supported() -> bool:
    global _has_varietal
    if _has_varietal is None:
        try:
            row = await fetch_one(
                """--sql
                SELECT 1 AS ok
                  FROM information_schema.columns
                 WHERE table_name = %s AND column_name = 'grape_varietal'
                 LIMIT 1
                """,
                [MAP_TABLE],
            )
            _has_varietal = row is not None
        except Exception:
            logger.warning("could not probe for map varietal support", exc_info=True)
            return False
    return _has_varietal


async def heat_index_available() -> bool:
    global _has_heat_index
    if _has_heat_index is None:
        try:
            row = await fetch_one(
                "SELECT to_regclass(%s) IS NOT NULL AS ok", [MAP_HEAT_INDEX]
            )
            _has_heat_index = bool(row and row["ok"])
        except Exception:
            logger.warning("could not probe for the map heat index", exc_info=True)
            return False
    return _has_heat_index


def _map_limiter() -> SlidingWindowLimiter:
    global _limiter
    if _limiter is None:
        settings = get_settings()
        _limiter = SlidingWindowLimiter(
            settings.map_rate_limit, settings.map_rate_window_seconds
        )
    return _limiter


def reset_limiter() -> None:
    global _limiter, _has_varietal, _has_heat_index
    _limiter = None
    _has_varietal = None
    _has_heat_index = None
    _grid_cache.clear()
    _grid_builds.clear()


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
    """Grid cell in degrees for a zoom level, at roughly 32 bins per tile.

    Halving with each zoom step keeps a bin the same size on screen however far
    in the user is, so the heat surface does not re-scale as they navigate.

    32 bins per tile puts bin centres 16 CSS px apart. The client rounds its
    zoom, so the real spacing runs 11-23 px, and the radius ramp below in
    MapView clears even the top of that; at 8 and 16 bins the sparse areas read
    as a lattice of separate dots rather than a surface.
    """
    z = min(max(zoom, 0), 16)
    return 360.0 / (2**z) / 32


def _wrap_longitude(value: float) -> float:
    """Fold a longitude into [-180, 180]; map panning runs past the edges."""
    return ((value + 180.0) % 360.0) - 180.0


def _normalise_viewport(
    west: float, south: float, east: float, north: float
) -> tuple[float, float, float, float, bool]:
    """Clamped, ordered latitudes and wrapped longitudes, plus whether the
    viewport spans the whole world (no longitude left to constrain)."""
    south = max(-90.0, min(90.0, south))
    north = max(-90.0, min(90.0, north))
    if north < south:
        south, north = north, south
    if east - west >= 360.0:
        return west, south, east, north, True
    return _wrap_longitude(west), south, _wrap_longitude(east), north, False


# ST_MakeEnvelope carries only four corners, and casting to geography turns its
# edges into great-circle arcs. In the northern hemisphere the southern edge
# bows poleward — at a continental viewport width that lifts it tens of degrees
# above the latitude asked for, worst at the centre longitude and nil at the
# corners, so the bottom of a wide viewport silently returns nothing. Densifying
# the edges first keeps each segment within a few hundred metres of its parallel.
ENVELOPE_SEGMENT_DEG = 1.0

_ENVELOPE = (
    "location && "
    "ST_Segmentize(ST_MakeEnvelope(%s, %s, %s, %s, 4326), %s)::geography"
)


def _bbox_condition(
    west: float, south: float, east: float, north: float, geography: bool = True
) -> tuple[str, list[Any]]:
    """Viewport predicate against the GiST-indexed geography column.

    The geography test is a bounding-box filter that rides the index; the plain
    latitude/longitude bounds alongside it are what make the result exact.
    With ``geography=False`` only the plain bounds are emitted, for the heat
    aggregate's index-only scan over the covering btree, which the geography
    column would pull back onto the heap.

    A viewport straddling the antimeridian arrives with west greater than east
    and has to be tested as two envelopes; one envelope spanning the difference
    would select the whole rest of the world instead.
    """
    west, south, east, north, whole = _normalise_viewport(west, south, east, north)

    lat = "latitude BETWEEN %s AND %s"

    # Zoomed out past a whole world there is no longitude left to constrain, and
    # a global envelope is the one shape geography handles worst.
    if whole:
        return lat, [south, north]

    if west > east:
        lng = f"(longitude >= %s OR longitude <= %s) AND {lat}"
        if not geography:
            return lng, [west, east, south, north]
        return (
            f"({_ENVELOPE} OR {_ENVELOPE}) AND {lng}",
            [
                west, south, 180.0, north, ENVELOPE_SEGMENT_DEG,
                -180.0, south, east, north, ENVELOPE_SEGMENT_DEG,
                west, east, south, north,
            ],
        )
    lng = f"longitude BETWEEN %s AND %s AND {lat}"
    if not geography:
        return lng, [west, east, south, north]
    return (
        f"{_ENVELOPE} AND {lng}",
        [west, south, east, north, ENVELOPE_SEGMENT_DEG, west, east, south, north],
    )


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
    varietal: str | None = None,
    geography: bool = True,
    viewport: bool = True,
) -> tuple[str, list[Any]]:
    """WHERE clause for a viewport query, and the parameters it binds.

    ``viewport=False`` drops the bounds altogether, for the world heat grid.
    """
    conditions: list[str] = []
    params: list[Any] = []
    if viewport:
        bbox_sql, params = _bbox_condition(west, south, east, north, geography)
        conditions.append(bbox_sql)
    conditions.append("location_role = %s")
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
    if varietal:
        # Partial match, as on the search endpoint: a COLA's varietal column is a
        # joined list, so an equality test would miss every blend.
        conditions.append("grape_varietal ILIKE %s")
        params.append(f"%{varietal}%")

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


async def _resolve_varietal(varietal: str | None) -> str | None:
    """Reject a varietal filter the surface cannot honour, rather than ignore it."""
    if not varietal:
        return None
    if not await varietal_supported():
        raise HTTPException(
            status_code=400,
            detail="Varietal is not filterable on the map in this environment.",
        )
    return varietal


def _unavailable(exc: Exception) -> HTTPException:
    """The map surface is built by a later pipeline stage than the search one."""
    logger.warning("map surface is not available", exc_info=exc)
    return HTTPException(
        status_code=503,
        detail="Map data has not been built for this environment yet.",
    )


async def _heat_bins(
    where: str, params: list[Any], cell: float
) -> tuple[list[MapHeatBin], int]:
    """Grid every row in the viewport, not a prefix of them.

    An unordered LIMIT here used to bound the scan, but it made the surface a
    lie: Postgres returns whichever rows the plan reaches first, so at national
    zoom whole regions dropped out and reappeared when the viewport nudged. The
    output is bounded by BIN_CAP instead. The total is a window over the bins
    rather than a second pass over the matched rows, which at national zoom
    materialised millions of them to temp just to count them.
    """
    rows = await fetch_all(
        f"""--sql
        WITH g AS (
            SELECT floor(longitude / %s) AS gx, floor(latitude / %s) AS gy,
                   count(*) AS n
              FROM {MAP_TABLE} {where}
             GROUP BY 1, 2
        )
        SELECT gx, gy, n, sum(n) OVER () AS scanned
          FROM g ORDER BY n DESC LIMIT %s
        """,
        [cell, cell, *params, BIN_CAP],
    )

    total = int(rows[0]["scanned"]) if rows else 0
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
    return bins, total


def _grid_key(zoom: int, role: str, filters: dict[str, Any]) -> GridKey:
    return zoom, role, tuple(sorted((k, str(v)) for k, v in filters.items() if v))


def _build_world_grid(
    key: GridKey, zoom: int, role: str, filters: dict[str, Any]
) -> asyncio.Task[GridCells]:
    """Start (or join) the one build of a world grid, caching what it returns.

    Runs as a task so a client that gives up mid-scan does not cancel the work
    every other viewport at this zoom is waiting on.
    """
    running = _grid_builds.get(key)
    if running is not None:
        return running

    settings = get_settings()
    where, params = build_map_filters(0, 0, 0, 0, role, **filters, viewport=False)
    cell = _cell_size(zoom)
    # Only the shared unfiltered grids get the long timeout; a filter is one
    # caller's choice and keeps the ordinary ceiling.
    timeout = None if key[2] else settings.map_heat_statement_timeout_ms

    async def build() -> GridCells:
        rows = await fetch_all(
            f"""--sql
            SELECT floor(longitude / %s) AS gx, floor(latitude / %s) AS gy,
                   count(*) AS n
              FROM {MAP_TABLE} {where}
             GROUP BY 1, 2
            """,
            [cell, cell, *params],
            statement_timeout_ms=timeout,
        )
        cells = [(int(r["gx"]), int(r["gy"]), int(r["n"])) for r in rows]
        _grid_cache[key] = (time.monotonic(), cells)
        _grid_cache.move_to_end(key)
        while len(_grid_cache) > settings.map_heat_cache_size:
            _grid_cache.popitem(last=False)
        return cells

    def finished(task: asyncio.Task[GridCells]) -> None:
        _grid_builds.pop(key, None)
        if not task.cancelled() and task.exception() is not None:
            logger.warning("map heat grid build failed for %r", key, exc_info=task.exception())

    task = asyncio.ensure_future(build())
    task.add_done_callback(finished)
    _grid_builds[key] = task
    return task


async def _world_grid(zoom: int, role: str, filters: dict[str, Any]) -> GridCells:
    """The whole-world grid for a zoom, served stale while it rebuilds.

    The surface only changes when the pipeline rebuilds it, so a grid a few
    minutes past its TTL is still right, and answering from it beats making
    the next visitor wait on the rebuild.
    """
    key = _grid_key(zoom, role, filters)
    hit = _grid_cache.get(key)
    if hit is not None:
        built_at, cells = hit
        _grid_cache.move_to_end(key)
        if time.monotonic() - built_at > get_settings().map_heat_cache_seconds:
            _build_world_grid(key, zoom, role, filters)
        return cells
    return await asyncio.shield(_build_world_grid(key, zoom, role, filters))


def _clip_grid(
    cells: GridCells, cell: float, west: float, south: float, east: float, north: float
) -> tuple[list[MapHeatBin], int]:
    """The world grid's cells that touch the viewport, densest first.

    The total is summed over whole cells, so at these zooms it can include a
    cell's worth of records just past the edge of the screen.
    """
    west, south, east, north, whole = _normalise_viewport(west, south, east, north)

    def lng_in_view(lo: float, hi: float) -> bool:
        if whole:
            return True
        if west <= east:
            return hi >= west and lo <= east
        return hi >= west or lo <= east

    kept = [
        (gx, gy, n)
        for gx, gy, n in cells
        if (gy + 1) * cell >= south and gy * cell <= north
        and lng_in_view(gx * cell, (gx + 1) * cell)
    ]
    total = sum(n for _gx, _gy, n in kept)
    kept.sort(key=lambda c: c[2], reverse=True)
    bins = [
        MapHeatBin(
            lng=round((gx + 0.5) * cell, 6),
            lat=round((gy + 0.5) * cell, 6),
            count=n,
        )
        for gx, gy, n in kept[:BIN_CAP]
    ]
    return bins, total


async def warm_heat_cache() -> None:
    """Build the default view's grids so the first visitor after a deploy does
    not wait on a cold scan. Sequential: the first build pulls the index into
    cache and the rest then run warm."""
    if not get_settings().map_heat_warm_on_startup:
        return
    for zoom in WARM_ZOOMS:
        try:
            await _world_grid(zoom, "primary_premise", {})
        except UndefinedTable:
            return
        except Exception:
            logger.warning("map heat warm-up failed at zoom %s", zoom, exc_info=True)
            return


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


@router.get(
    "/map/points",
    response_model=MapPointsResponse,
    summary="Points or heat bins for a map viewport",
    responses={
        400: {"description": "Unknown `mode` or `role`, or a varietal filter the surface cannot apply."},
        429: {"description": "Too many map requests from one caller."},
        503: {"description": "The map surface has not been built in this environment."},
    },
)
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
                "`heat` aggregates the viewport onto a grid and returns `bins` with "
                "counts. `image` returns individual COLAs as `points` with a label "
                "thumbnail, capped so the map stays readable."
            ),
            json_schema_extra={"enum": list(MODES)},
        ),
    ] = "heat",
    role: RoleParam = "primary_premise",
    commodity: CommodityParam = None,
    source: SourceParam = None,
    origin: OriginParam = None,
    class_type: ClassTypeParam = None,
    date_from: DateFromParam = None,
    date_to: DateToParam = None,
    varietal: VarietalParam = None,
) -> MapPointsResponse:
    """Everything in a rectangular viewport, aggregated or listed.

    A viewport at low zoom can cover millions of rows, so `heat` mode is the
    default: it grids them server-side and returns at most 20,000 bins, ordered
    by count. `image` mode returns individual COLAs instead and is meant for
    viewports already narrow enough to draw. Either way `total` is the number of
    rows matched, and `totalIsCapped` says whether that number is a floor.
    """
    _enforce_rate_limit(request)
    _validate(role, mode)

    settings = get_settings()
    supports_varietal = await varietal_supported()
    filters: dict[str, Any] = {
        "commodity": commodity,
        "source": source,
        "origin": origin,
        "class_type": class_type,
        "date_from": date_from,
        "date_to": date_to,
        "varietal": await _resolve_varietal(varietal),
    }

    try:
        if mode == "image":
            where, params = build_map_filters(
                west, south, east, north, role, **filters, geography=True
            )
            points = await _image_points(where, params, settings.map_image_point_cap)
            return MapPointsResponse(
                mode=mode,
                role=role,
                points=points,
                total=len(points),
                total_is_capped=len(points) >= settings.map_image_point_cap,
                varietal_available=supports_varietal,
            )

        cell = _cell_size(zoom)
        if zoom <= WORLD_GRID_MAX_ZOOM:
            cells = await _world_grid(zoom, role, filters)
            bins, total = _clip_grid(cells, cell, west, south, east, north)
        else:
            where, params = build_map_filters(
                west, south, east, north, role, **filters,
                geography=not await heat_index_available(),
            )
            bins, total = await _heat_bins(where, params, cell)
    except UndefinedTable as exc:
        raise _unavailable(exc) from exc

    return MapPointsResponse(
        mode=mode,
        role=role,
        bins=bins,
        total=total,
        total_is_capped=False,
        varietal_available=supports_varietal,
    )


@router.get(
    "/map/area",
    response_model=MapAreaResponse,
    summary="Summarise one selected area of the map",
    responses={
        400: {"description": "Unknown `role`, or a varietal filter the surface cannot apply."},
        429: {"description": "Too many map requests from one caller."},
        503: {"description": "The map surface has not been built in this environment."},
    },
)
async def map_area(
    request: Request,
    west: Annotated[float, Query(description="Selection west longitude.")],
    south: Annotated[float, Query(description="Selection south latitude.")],
    east: Annotated[float, Query(description="Selection east longitude.")],
    north: Annotated[float, Query(description="Selection north latitude.")],
    role: RoleParam = "primary_premise",
    commodity: CommodityParam = None,
    source: SourceParam = None,
    origin: OriginParam = None,
    class_type: ClassTypeParam = None,
    date_from: DateFromParam = None,
    date_to: DateToParam = None,
    varietal: VarietalParam = None,
    page: Annotated[
        int,
        Query(
            ge=1,
            le=100,
            description=f"1-based page of the `items` list, {AREA_PAGE_SIZE} per page.",
        ),
    ] = 1,
) -> MapAreaResponse:
    """Counts and facet breakdowns for a selected rectangle, plus the COLAs in it.

    Takes the same filters as `/map/points` so a selection summarises exactly
    what is drawn. `total` is capped by a scan limit; when `totalIsCapped` is
    true the counts and facets describe a bounded sample rather than the whole
    selection.
    """
    _enforce_rate_limit(request)
    _validate(role)

    settings = get_settings()
    cap = settings.map_scan_cap
    where, params = build_map_filters(
        west, south, east, north, role, commodity, source, origin,
        class_type, date_from, date_to, await _resolve_varietal(varietal),
    )

    # Same shape as the search facets: one materialised CTE, scanned once and
    # rolled up across every dimension.
    summary_sql = f"""--sql
    WITH m AS (
        SELECT ct_commodity, ct_source, origin, class_type
          FROM {MAP_TABLE} {where} LIMIT %s
    )
    SELECT 'commodity' AS dim, ct_commodity AS value, NULL::text AS parent,
           count(*) AS count FROM m GROUP BY 1, 2, 3
    UNION ALL SELECT 'source', ct_source, NULL, count(*) FROM m GROUP BY 1, 2, 3
    UNION ALL SELECT 'origin', origin, ct_source, count(*) FROM m GROUP BY 1, 2, 3
    UNION ALL SELECT 'classType', class_type, NULL, count(*) FROM m GROUP BY 1, 2, 3
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
    count_sql = f"""--sql
    SELECT count(*) AS n, count(DISTINCT permit_id) AS permit_count
        FROM (SELECT permit_id FROM {MAP_TABLE} {where} LIMIT %s) t
    """

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

    def source_groups() -> list[FacetGroup]:
        # Totals are summed after labelling because source_label collapses the
        # 'import' and 'unknown' codes onto one label.
        totals: Counter[str] = Counter()
        for row in grouped.get("source", []):
            if row["value"]:
                totals[source_label(row["value"])] += row["count"]

        children: dict[str, Counter[str]] = defaultdict(Counter)
        for row in grouped.get("origin", []):
            if row["value"] and row["parent"]:
                children[source_label(row["parent"])][row["value"]] += row["count"]

        return [
            FacetGroup(
                value=label,
                count=count,
                children=[
                    FacetBucket(value=origin, count=n)
                    for origin, n in children[label].most_common()
                ],
            )
            for label, count in totals.most_common()
        ]

    raw_total = int(total_row["n"]) if total_row else 0
    capped = raw_total > cap

    return MapAreaResponse(
        total=cap if capped else raw_total,
        total_is_capped=capped,
        permit_count=int(total_row.get("permit_count") or 0) if total_row else 0,
        commodity=buckets("commodity", commodity_label),
        source=source_groups(),
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
        logger.warning(
            "basemap read failed for range %r", request.headers.get("range"), exc_info=True
        )
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
