"""Temporary diagnostic: map surface size, indexes, and EXPLAIN ANALYZE of the
heat/area statements for the viewports the SPA actually sends."""
import asyncio
import os
import sys
import time
from datetime import date
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

load_dotenv()

from api.db import close_pool, fetch_all, open_pool, transaction_cursor  # noqa: E402
from api.mappers import MAP_TABLE  # noqa: E402
from api.routers.map import BIN_CAP, _cell_size, build_map_filters  # noqa: E402

ONLY = set(os.environ.get("DIAG_ONLY", "").split(",")) - {""}


def hr(title: str) -> None:
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)


def table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("(no rows)")
        return
    cols = list(rows[0].keys())
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    print(" | ".join(c.ljust(widths[c]) for c in cols))
    print("-+-".join("-" * widths[c] for c in cols))
    for r in rows:
        print(" | ".join(str(r[c]).ljust(widths[c]) for c in cols))


async def sizes() -> None:
    hr("MAP SURFACE")
    table(await fetch_all(
        """--sql
        SELECT c.relname AS table, c.relpages, c.relallvisible,
               round(100.0 * c.relallvisible / greatest(c.relpages, 1)) AS pct_allvisible,
               s.n_tup_ins, s.n_tup_upd, s.n_tup_hot_upd, s.n_tup_del, s.n_live_tup, s.n_dead_tup,
               s.last_vacuum::timestamp(0), s.last_autovacuum::timestamp(0), s.autovacuum_count
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
          LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
         WHERE n.nspname = current_schema() AND c.relname = %s
        """, [MAP_TABLE]))
    table(await fetch_all(
        """--sql
        SELECT name, setting FROM pg_settings
         WHERE name IN ('autovacuum_vacuum_scale_factor','autovacuum_vacuum_threshold',
                        'autovacuum_vacuum_insert_scale_factor','autovacuum_naptime',
                        'max_parallel_workers_per_gather','work_mem','maintenance_work_mem')
        """))
    table(await fetch_all(
        """--sql
        SELECT c.relname AS table, c.relkind,
               to_char(c.reltuples, 'FM999,999,999,999') AS est_rows,
               pg_size_pretty(pg_table_size(c.oid)) AS heap_toast,
               pg_size_pretty(pg_indexes_size(c.oid)) AS indexes,
               s.n_dead_tup, s.last_autovacuum::timestamp(0), s.last_autoanalyze::timestamp(0)
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
          LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
         WHERE n.nspname = current_schema() AND c.relname = %s
        """, [MAP_TABLE]))
    table(await fetch_all(
        """--sql
        SELECT i.relname AS index, pg_size_pretty(pg_relation_size(i.oid)) AS size,
               s.idx_scan, left(pg_get_indexdef(i.oid), 200) AS def
          FROM pg_index x
          JOIN pg_class i ON i.oid = x.indexrelid
          JOIN pg_class t ON t.oid = x.indrelid
          JOIN pg_namespace n ON n.oid = t.relnamespace
          LEFT JOIN pg_stat_user_indexes s ON s.indexrelid = i.oid
         WHERE n.nspname = current_schema() AND t.relname = %s
         ORDER BY s.idx_scan DESC NULLS LAST
        """, [MAP_TABLE]))
    table(await fetch_all(
        """--sql
        SELECT column_name, data_type FROM information_schema.columns
         WHERE table_schema = current_schema() AND table_name = %s ORDER BY ordinal_position
        """, [MAP_TABLE]))
    table(await fetch_all(
        f"SELECT location_role, count(*) * 100 AS est FROM {MAP_TABLE} TABLESAMPLE SYSTEM (1) GROUP BY 1 ORDER BY 2 DESC"))


async def explain(label: str, sql: str, params: list[Any]) -> None:
    print(f"\n--- {label} ---")
    async with transaction_cursor() as cur:
        await cur.execute("SET LOCAL statement_timeout TO '180s'")
        t0 = time.perf_counter()
        try:
            await cur.execute("EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT TEXT) " + sql, params)
            rows = await cur.fetchall()
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED after {time.perf_counter()-t0:.1f}s: {exc}")
            return
    print(f"wall {(time.perf_counter() - t0)*1000:.0f} ms")
    for r in rows:
        print("  " + list(r.values())[0])


VIEWPORTS = {
    # The failing default view from App Insights.
    "default_z3": (-179.99999999989967, 6.855032678204125, -11.013884945545442, 60.60497277804302, 3),
    "conus_z4": (-125.0, 24.0, -66.0, 50.0, 4),
    "california_z6": (-125.0, 32.0, -114.0, 42.0, 6),
    "napa_z10": (-122.6, 38.1, -122.1, 38.6, 10),
}


def heat_sql(where: str) -> str:
    return f"""--sql
    WITH m AS (
        SELECT latitude, longitude FROM {MAP_TABLE} {where}
    ), g AS (
        SELECT floor(longitude / %s) AS gx, floor(latitude / %s) AS gy, count(*) AS n
          FROM m GROUP BY 1, 2
    )
    SELECT gx, gy, n, (SELECT count(*) FROM m) AS scanned
      FROM g ORDER BY n DESC LIMIT %s
    """


async def heat() -> None:
    hr("/map/points heat — current statement")
    for name, (w, s, e, n, z) in VIEWPORTS.items():
        if ONLY and name not in ONLY:
            continue
        for role in ("primary_premise", "product_origin"):
            where, params = build_map_filters(w, s, e, n, role)
            cell = _cell_size(z)
            await explain(f"{name} role={role}", heat_sql(where), [*params, cell, cell, BIN_CAP])


async def variants() -> None:
    hr("/map/points heat — variants for the default viewport")
    w, s, e, n, z = VIEWPORTS["default_z3"]
    cell = _cell_size(z)
    where, params = build_map_filters(w, s, e, n, "primary_premise")

    await explain("A: bbox only, count(*)", f"SELECT count(*) FROM {MAP_TABLE} {where}", params)

    lat_lng_where = (
        "WHERE longitude BETWEEN %s AND %s AND latitude BETWEEN %s AND %s AND location_role = %s"
    )
    await explain("B: plain lat/lng between, count(*)",
                  f"SELECT count(*) FROM {MAP_TABLE} {lat_lng_where}",
                  [w, e, s, n, "primary_premise"])

    await explain("C: grouping without the scalar subquery re-scan",
                  f"""--sql
                  SELECT floor(longitude / %s) AS gx, floor(latitude / %s) AS gy, count(*) AS n
                    FROM {MAP_TABLE} {where}
                   GROUP BY 1, 2 ORDER BY n DESC LIMIT %s
                  """, [cell, cell, *params, BIN_CAP])

    await explain("D: grouping over plain lat/lng between",
                  f"""--sql
                  SELECT floor(longitude / %s) AS gx, floor(latitude / %s) AS gy, count(*) AS n
                    FROM {MAP_TABLE} {lat_lng_where}
                   GROUP BY 1, 2 ORDER BY n DESC LIMIT %s
                  """, [cell, cell, w, e, s, n, "primary_premise", BIN_CAP])


HEAT_INDEX_SQL = f"""--sql
CREATE INDEX CONCURRENTLY IF NOT EXISTS cola_map_search_heat_idx
    ON {MAP_TABLE} (location_role, latitude, longitude)
    INCLUDE (ct_commodity, ct_source, origin, class_type_code, class_type, completed_date)
"""


async def create_heat_index() -> None:
    """CONCURRENTLY cannot run inside a transaction, and the pooled session
    carries the 15 s statement timeout, so this uses a raw autocommit cursor."""
    hr("CREATE cola_map_search_heat_idx")
    from api.db import get_pool
    async with get_pool().connection() as conn, conn.cursor() as cur:
        await cur.execute("SET statement_timeout TO 0")
        await cur.execute("SET maintenance_work_mem TO '1GB'")
        t0 = time.perf_counter()
        await cur.execute(HEAT_INDEX_SQL)
        print(f"created in {time.perf_counter() - t0:.0f}s")
        await cur.execute(
            """--sql
            SELECT indexrelid::regclass AS index, indisvalid, pg_size_pretty(pg_relation_size(indexrelid)) AS size
              FROM pg_index WHERE indexrelid = to_regclass('cola_map_search_heat_idx')
            """)
        table(await cur.fetchall())


async def heat_new() -> None:
    hr("/map/points heat — proposed statement (lat/lng bounds only, window total)")
    for name, (w, s, e, n, z) in VIEWPORTS.items():
        if ONLY and name not in ONLY:
            continue
        cell = _cell_size(z)
        for role, extra in (("primary_premise", {}), ("product_origin", {}),
                            ("primary_premise", {"commodity": "wine", "date_from": date(2020, 1, 1)})):
            where, params = build_map_filters(w, s, e, n, role, geography=False, **extra)
            await explain(
                f"{name} role={role} {extra or ''}",
                f"""--sql
                WITH g AS (
                    SELECT floor(longitude / %s) AS gx, floor(latitude / %s) AS gy, count(*) AS n
                      FROM {MAP_TABLE} {where}
                     GROUP BY 1, 2
                )
                SELECT gx, gy, n, sum(n) OVER () AS scanned
                  FROM g ORDER BY n DESC LIMIT %s
                """,
                [cell, cell, *params, BIN_CAP])


async def main() -> None:
    await open_pool()
    sections = {"sizes": sizes, "heat": heat, "variants": variants, "index": create_heat_index,
                "heat_new": heat_new}
    wanted = set(os.environ.get("DIAG_SECTIONS", "sizes,heat,variants").split(","))
    for name, fn in sections.items():
        if name in wanted:
            await fn()
    await close_pool()


asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
