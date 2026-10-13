"""Why does the default (national heat) map view time out? VM state + EXPLAIN of the z3 query."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

load_dotenv()
from api.db import close_pool, fetch_all, open_pool  # noqa: E402
from api.mappers import MAP_HEAT_INDEX, MAP_TABLE  # noqa: E402
from api.routers.map import _cell_size, build_map_filters  # noqa: E402


async def main() -> None:
    await open_pool()
    for r in await fetch_all(
        """--sql
        SELECT c.relname, c.relpages, c.relallvisible,
               round(100.0 * c.relallvisible / greatest(c.relpages, 1), 1) AS pct_visible,
               s.n_live_tup, s.n_dead_tup, s.n_mod_since_analyze, s.n_ins_since_vacuum,
               s.last_vacuum, s.last_autovacuum, s.last_analyze, s.last_autoanalyze
          FROM pg_class c JOIN pg_stat_user_tables s ON s.relid = c.oid
         WHERE c.relname = %s
        """,
        [MAP_TABLE],
    ):
        print(dict(r))
    for r in await fetch_all(
        "SELECT pg_size_pretty(pg_relation_size(to_regclass(%s))) AS heat_idx", [MAP_HEAT_INDEX]
    ):
        print(dict(r))

    zoom = int(os.environ.get("DIAG_ZOOM", "3"))
    west, south, east, north = (
        float(x) for x in os.environ.get("DIAG_BBOX", "-140,14,-52,56").split(",")
    )
    where, params = build_map_filters(
        west, south, east, north, "primary_premise", geography=False
    )
    cell = _cell_size(zoom)
    rows = await fetch_all(
        f"""--sql
        EXPLAIN (ANALYZE, BUFFERS)
        WITH g AS (
            SELECT floor(longitude / %s) AS gx, floor(latitude / %s) AS gy, count(*) AS n
              FROM {MAP_TABLE} {where}
             GROUP BY 1, 2
        )
        SELECT gx, gy, n, sum(n) OVER () AS scanned FROM g ORDER BY n DESC LIMIT 20000
        """,
        [cell, cell, *params],
    )
    for r in rows:
        print(r["QUERY PLAN"])

    import time

    from api.routers import map as map_router

    for z in map_router.WARM_ZOOMS:
        started = time.perf_counter()
        cells = await map_router._world_grid(z, "primary_premise", {})
        print(f"world grid z{z}: {len(cells)} cells, {sum(c[2] for c in cells)} rows, "
              f"{time.perf_counter() - started:.1f}s")
    await close_pool()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
