"""One-off: cost of exact per-value counts for the class/type and varietal typeaheads."""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

load_dotenv()
from api.db import close_pool, fetch_all, open_pool  # noqa: E402

PROBES = [
    (
        "class_type_code group (index)",
        """--sql
        SELECT class_type_code, count(*) AS n FROM cola_search
         WHERE class_type_code IS NOT NULL GROUP BY 1
        """,
    ),
    (
        "class_type text group",
        """--sql
        SELECT class_type, count(*) AS n FROM cola_search
         WHERE class_type IS NOT NULL GROUP BY 1
        """,
    ),
    (
        "varietal group (base table)",
        """--sql
        SELECT vartl_name, count(*) AS n FROM cola_grape_varietals
         WHERE vartl_name IS NOT NULL GROUP BY 1
        """,
    ),
    (
        "varietal group (cola_search join)",
        """--sql
        SELECT g.vartl_name, count(*) AS n
          FROM cola_grape_varietals g JOIN cola_search s USING (cola_id)
         GROUP BY 1
        """,
    ),
]


async def main() -> None:
    await open_pool()
    for row in await fetch_all(
        """--sql
        SELECT relname, n_live_tup, pg_size_pretty(pg_total_relation_size(relid)) AS size,
               last_autovacuum, last_vacuum
          FROM pg_stat_user_tables
         WHERE relname IN ('cola_search', 'cola_grape_varietals')
        """
    ):
        print(dict(row))
    for label, sql in PROBES:
        t = time.perf_counter()
        try:
            rows = await fetch_all(sql, statement_timeout_ms=120_000, prepare=False)
            top = sorted(rows, key=lambda r: r["n"], reverse=True)[:3]
            print(f"{label}: {len(rows)} groups in {time.perf_counter() - t:.2f}s; top {[tuple(r.values()) for r in top]}")
        except Exception as e:  # noqa: BLE001
            print(f"{label}: {type(e).__name__} after {time.perf_counter() - t:.2f}s")
    await close_pool()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
