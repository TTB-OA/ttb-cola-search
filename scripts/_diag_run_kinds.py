"""One-off: what the running backfill writes for e-filed vs paper COLAs, against rows it hasn't reached."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

load_dotenv()
from api.db import close_pool, fetch_all, open_pool  # noqa: E402

LAUNCHED = os.environ.get("DIAG_LAUNCHED", "2026-10-12 22:46:07+00")
DATE_FROM = os.environ.get("DIAG_FROM", "2010-01-01")
DATE_TO = os.environ.get("DIAG_TO", "2011-01-01")


async def main() -> None:
    await open_pool()
    print(f"completed {DATE_FROM}..{DATE_TO}, imaged; 'this run' = form_scraped_on >= {LAUNCHED}")
    for r in await fetch_all(
        """--sql
        SELECT CASE WHEN received_code = 'ES' THEN 'e-filed' ELSE 'paper' END AS kind,
               CASE WHEN form_scraped_on >= %s::timestamptz THEN 'this run' ELSE 'not yet' END AS state,
               count(*) AS n,
               count(*) FILTER (WHERE form_view = 'form') AS form_view,
               count(*) FILTER (WHERE form_view = 'search') AS search_view,
               count(application_type) AS appl_type,
               count(type_of_product) AS type_prod,
               count(application_date) AS appl_date,
               count(printed_name) AS printed_name,
               count(applicant_phone) AS phone,
               count(formula_num) AS formula,
               count(wine_vintage) AS vintage,
               count(appellation) AS appellation
          FROM colas
         WHERE completed_date >= %s AND completed_date < %s
           AND image_count_to_parse > 0
         GROUP BY 1, 2 ORDER BY 1, 2
        """,
        [LAUNCHED, DATE_FROM, DATE_TO],
    ):
        print("  " + "  ".join(f"{k}={v}" for k, v in dict(r).items()))
    await close_pool()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
