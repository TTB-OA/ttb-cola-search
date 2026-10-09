"""One-off: progress and rate of the 2025+ form-field backfill on prod."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

load_dotenv()
from api.db import close_pool, fetch_all, open_pool  # noqa: E402

LAUNCHED = "2026-10-09 00:50:42+00"


async def main() -> None:
    await open_pool()
    r = (await fetch_all(
        """--sql
        SELECT count(*) FILTER (WHERE c.form_scraped_on >= %s::timestamptz) AS done,
               min(c.form_scraped_on) FILTER (WHERE c.form_scraped_on >= %s::timestamptz) AS first_at,
               max(c.form_scraped_on) AS last_at,
               count(*) FILTER (WHERE c.form_scraped_on >= now() - interval '10 minutes') AS last_10m,
               now() AS now
          FROM colas c
         WHERE c.completed_date >= '2025-01-01'
        """,
        [LAUNCHED, LAUNCHED],
    ))[0]
    print(dict(r))
    q = (await fetch_all("SELECT count(*) AS n FROM cola_search_dirty"))[0]
    print("dirty queue:", q["n"])
    fill = (await fetch_all(
        """--sql
        SELECT count(*) AS n,
               count(*) FILTER (WHERE form_scraped_on IS NULL) AS unread,
               count(formula_num) AS formula, count(appellation) AS appellation,
               count(applicant_phone) AS phone, count(applicant_email) AS email,
               count(container_text) AS item15, count(printed_name) AS printed_name,
               count(*) FILTER (WHERE ttb_signed) AS ttb_signed
          FROM colas
         WHERE completed_date >= '2025-01-01' AND received_code = 'ES'
        """
    ))[0]
    print("colas ES 2025+:", dict(fill))
    surf = (await fetch_all(
        """--sql
        SELECT count(*) AS n, count(printed_name) AS printed_name, count(formula) AS formula
          FROM cola_search
         WHERE completed_date >= '2025-01-01' AND received_code = 'ES'
        """
    ))[0]
    print("cola_search ES 2025+:", dict(surf))
    for r in await fetch_all(
        """--sql
        SELECT appellation, type_of_product, count(*) AS n
          FROM colas
         WHERE completed_date >= '2025-01-01' AND received_code = 'ES'
           AND appellation IS NOT NULL
         GROUP BY 1, 2 ORDER BY n DESC LIMIT 15
        """
    ):
        print("  ", dict(r))
    await close_pool()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
