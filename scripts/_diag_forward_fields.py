"""One-off: did forward (scheduled) ingestion fill the form fields for COLAs completed after a date?"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

load_dotenv()
from api.db import close_pool, fetch_all, open_pool  # noqa: E402

SINCE = os.environ.get("DIAG_SINCE", "2026-09-15")
# Pipeline deploy of the form-field scrape; images first fetched after this
# were read by the scheduled legs, not the manual backfill.
DEPLOYED = os.environ.get("DIAG_DEPLOYED", "2026-10-09 00:00+00")


async def main() -> None:
    await open_pool()
    print(f"COLAs completed >= {SINCE} whose first image row is newer than {DEPLOYED}")
    for r in await fetch_all(
        """--sql
        WITH fwd AS (
            SELECT c.*
              FROM colas c
             WHERE c.completed_date >= %s
               AND (SELECT min(i.scraped_on) FROM cola_images i WHERE i.cola_id = c.cola_id)
                   >= %s::timestamptz
        )
        SELECT c.received_code,
               count(*) AS n,
               count(c.form_scraped_on) AS form_read,
               count(*) FILTER (WHERE c.form_view = 'form') AS form_view,
               count(*) FILTER (WHERE c.form_view = 'search') AS search_view,
               count(c.printed_name) AS printed_name,
               count(c.applicant_phone) AS phone,
               count(c.application_date) AS appl_date,
               count(c.type_of_product) AS type_of_product,
               count(c.formula_num) AS formula,
               count(c.appellation) AS appellation,
               count(*) FILTER (WHERE c.ttb_signed) AS ttb_signed,
               count(*) FILTER (WHERE EXISTS (SELECT 1 FROM cola_scan_extraction x WHERE x.cola_id = c.cola_id)) AS scan_read
          FROM fwd c
         GROUP BY 1 ORDER BY n DESC
        """,
        [SINCE, DEPLOYED],
    ):
        print("  " + "  ".join(f"{k}={v}" for k, v in dict(r).items()))
    await close_pool()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
