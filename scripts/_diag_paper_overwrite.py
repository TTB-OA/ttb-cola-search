"""One-off: did the search-view write on paper rows overwrite values scan_extract had filled?"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

load_dotenv()
from api.db import close_pool, fetch_all, open_pool  # noqa: E402

LAUNCHED = os.environ.get("DIAG_LAUNCHED", "2026-10-12 22:46:07+00")


async def main() -> None:
    await open_pool()
    r = (await fetch_all(
        """--sql
        WITH done AS (
            SELECT c.cola_id, c.application_type, c.type_of_product,
                   x.metadata -> 'form_flags' AS scan
              FROM colas c
              JOIN cola_scan_extraction x USING (cola_id)
             WHERE c.completed_date >= '2010-01-01' AND c.completed_date < '2011-01-01'
               AND c.received_code <> 'ES'
               AND c.form_scraped_on >= %s::timestamptz
        )
        SELECT count(*) AS scanned_and_reread,
               count(*) FILTER (WHERE scan ->> 'application_type' IS NOT NULL) AS scan_had_appl_type,
               count(*) FILTER (WHERE scan ->> 'application_type' IS NOT NULL
                                  AND application_type IS DISTINCT FROM scan ->> 'application_type') AS appl_type_changed,
               count(*) FILTER (WHERE scan ->> 'type_of_product' IS NOT NULL) AS scan_had_type_prod,
               count(*) FILTER (WHERE scan ->> 'type_of_product' IS NOT NULL AND type_of_product IS NULL) AS type_prod_lost
          FROM done
        """,
        [LAUNCHED],
    ))[0]
    print(dict(r))
    for row in await fetch_all(
        """--sql
        SELECT c.application_type AS now, x.metadata -> 'form_flags' ->> 'application_type' AS scan, count(*) AS n
          FROM colas c JOIN cola_scan_extraction x USING (cola_id)
         WHERE c.completed_date >= '2010-01-01' AND c.completed_date < '2011-01-01'
           AND c.received_code <> 'ES' AND c.form_scraped_on >= %s::timestamptz
           AND c.application_type IS DISTINCT FROM x.metadata -> 'form_flags' ->> 'application_type'
         GROUP BY 1, 2 ORDER BY n DESC LIMIT 6
        """,
        [LAUNCHED],
    ):
        print("  ", dict(row))
    for row in await fetch_all(
        """--sql
        SELECT c.cola_id, c.for_sale_in, c.exemption_state
          FROM colas c JOIN cola_scan_extraction x USING (cola_id)
         WHERE c.completed_date >= '2010-01-01' AND c.completed_date < '2011-01-01'
           AND c.received_code <> 'ES' AND c.form_scraped_on >= %s::timestamptz
           AND x.metadata -> 'form_flags' ->> 'application_type' LIKE '%%EXEMPTION%%'
         LIMIT 3
        """,
        [LAUNCHED],
    ):
        print("  exemption sample:", dict(row))
    await close_pool()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
