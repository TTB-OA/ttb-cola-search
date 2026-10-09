"""One-off: does the TTB ID's YYJJJ prefix match the scraped application_date?"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

load_dotenv()
from api.db import close_pool, fetch_all, open_pool


async def main() -> None:
    await open_pool()
    rows = await fetch_all(
        """--sql
        WITH s AS (
            SELECT cola_id, received_code, application_date, completed_date,
                   CASE WHEN cola_id ~ '^[0-9]{5}'
                        THEN make_date(
                                 CASE WHEN left(cola_id, 2)::int <= 50 THEN 2000 ELSE 1900 END
                                     + left(cola_id, 2)::int, 1, 1)
                             + (substr(cola_id, 3, 3)::int - 1)
                   END AS derived
              FROM colas TABLESAMPLE SYSTEM (0.5)
             WHERE application_date IS NOT NULL
        )
        SELECT received_code,
               count(*) AS n,
               count(*) FILTER (WHERE derived = application_date) AS same,
               count(*) FILTER (WHERE derived <> application_date) AS diff,
               count(*) FILTER (WHERE derived IS NULL) AS unparsed,
               count(*) FILTER (WHERE derived > completed_date) AS after_completed,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY derived - application_date)
                   FILTER (WHERE derived <> application_date) AS med_gap_days
          FROM s GROUP BY 1 ORDER BY n DESC
        """
    )
    for r in rows:
        print(dict(r))
    for r in await fetch_all(
        """--sql
        SELECT cola_id, received_code, application_date, completed_date
          FROM colas TABLESAMPLE SYSTEM (0.5)
         WHERE cola_id !~ '^[0-9]{5}' LIMIT 10
        """
    ):
        print("odd id:", dict(r))
    for r in await fetch_all(
        """--sql
        SELECT min(left(cola_id, 2)) AS lo, max(left(cola_id, 2)) AS hi,
               min(completed_date) AS first_completed
          FROM colas TABLESAMPLE SYSTEM (0.5)
         WHERE left(cola_id, 2)::text ~ '^[5-9][0-9]$'
        """
    ):
        print("1900s ids:", dict(r))
    await close_pool()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
