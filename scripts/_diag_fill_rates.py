"""One-off: fill rates of the form fields for e-filed COLAs in a completed_date range (2% sample)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

load_dotenv()
from api.db import close_pool, fetch_all, open_pool  # noqa: E402

DATE_FROM = os.environ.get("DIAG_FROM", "2020-01-01")
DATE_TO = os.environ.get("DIAG_TO", "2025-01-01")


async def main() -> None:
    await open_pool()
    r = (await fetch_all(
        """--sql
        SELECT count(*) AS n,
               count(*) FILTER (WHERE form_scraped_on IS NULL AND image_count_to_parse > 0) AS unread_imaged,
               count(*) FILTER (WHERE form_scraped_on IS NULL) AS unread,
               count(formula_num) AS formula, count(appellation) AS appellation,
               count(*) FILTER (WHERE type_of_product = 'WINE') AS wine,
               count(applicant_phone) AS phone, count(container_text) AS item15,
               count(printed_name) AS printed_name, count(*) FILTER (WHERE ttb_signed) AS ttb_signed,
               count(application_date) AS application_date
          FROM colas TABLESAMPLE SYSTEM (2)
         WHERE completed_date >= %s AND completed_date < %s AND received_code = 'ES'
        """,
        [DATE_FROM, DATE_TO],
    ))[0]
    n = r["n"] or 1
    print(f"ES {DATE_FROM}..{DATE_TO}, 2% sample of {r['n']:,} rows")
    for key in ("unread_imaged", "unread", "printed_name", "phone", "ttb_signed",
                "application_date", "wine", "appellation", "item15", "formula"):
        print(f"  {key:17} {100 * r[key] / n:5.1f}%")
    await close_pool()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
