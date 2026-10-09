"""One-off: fill rates, indexes and plans for formula/appellation/application_date filters."""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

load_dotenv()
from api.db import close_pool, fetch_all, open_pool  # noqa: E402


async def main() -> None:
    await open_pool()
    r = (await fetch_all(
        """--sql
        SELECT count(*) AS n,
               count(*) FILTER (WHERE formula IS NOT NULL AND btrim(formula) <> '') AS formula,
               count(*) FILTER (WHERE appellation IS NOT NULL AND btrim(appellation) <> '') AS appellation,
               count(*) FILTER (WHERE application_date IS NOT NULL) AS application_date
          FROM cola_search TABLESAMPLE SYSTEM (1)
        """
    ))[0]
    print("sample (1%):", dict(r))
    for row in await fetch_all(
        """--sql
        SELECT indexname, indexdef FROM pg_indexes
         WHERE tablename = 'cola_search'
           AND (indexdef ILIKE '%%formula%%' OR indexdef ILIKE '%%appellation%%'
                OR indexdef ILIKE '%%application_date%%')
        """
    ):
        print("index:", row["indexname"], row["indexdef"])
    for row in await fetch_all(
        """--sql
        SELECT appellation, count(*) AS n FROM cola_search TABLESAMPLE SYSTEM (2)
         WHERE appellation IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 12
        """
    ):
        print("appellation:", row["appellation"], row["n"])
    for row in await fetch_all(
        """--sql
        SELECT formula FROM cola_search TABLESAMPLE SYSTEM (1)
         WHERE formula IS NOT NULL AND btrim(formula) <> '' LIMIT 12
        """
    ):
        print("formula:", repr(row["formula"]))
    probes = [
        ("formula tsv", "SELECT cola_id FROM cola_search WHERE search_tsv @@ websearch_to_tsquery('english', %s) AND formula ILIKE %s ORDER BY completed_date DESC NULLS LAST, cola_id DESC LIMIT 25", ["1600940", "%1600940%"]),
        ("appellation tsv", "SELECT cola_id FROM cola_search WHERE search_tsv @@ websearch_to_tsquery('english', %s) AND appellation ILIKE %s ORDER BY completed_date DESC NULLS LAST, cola_id DESC LIMIT 25", ["Willamette Valley", "%Willamette Valley%"]),
        ("appellation rare tsv", "SELECT cola_id FROM cola_search WHERE search_tsv @@ websearch_to_tsquery('english', %s) AND appellation ILIKE %s ORDER BY completed_date DESC NULLS LAST, cola_id DESC LIMIT 25", ["Mosel", "%Mosel%"]),
        ("application_date", "SELECT cola_id FROM cola_search WHERE application_date >= %s AND application_date <= %s ORDER BY completed_date DESC NULLS LAST, cola_id DESC LIMIT 25", ["2025-03-01", "2025-03-07"]),
        ("application_date old", "SELECT cola_id FROM cola_search WHERE application_date >= %s AND application_date <= %s ORDER BY completed_date DESC NULLS LAST, cola_id DESC LIMIT 25", ["2010-03-01", "2010-03-07"]),
    ]
    for label, sql, params in probes:
        t = time.perf_counter()
        try:
            rows = await fetch_all(sql, params, prepare=False)
            print(f"{label}: {len(rows)} rows in {time.perf_counter() - t:.2f}s")
        except Exception as e:  # noqa: BLE001
            print(f"{label}: {type(e).__name__} after {time.perf_counter() - t:.2f}s")
    await close_pool()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
