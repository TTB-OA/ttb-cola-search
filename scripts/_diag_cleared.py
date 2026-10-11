"""One-off: rows whose form read was cleared by a status change (read before, form_scraped_on now NULL)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

load_dotenv()
from api.db import close_pool, fetch_all, open_pool  # noqa: E402


async def main() -> None:
    await open_pool()
    for r in await fetch_all(
        """--sql
        SELECT completed_date, status, received_code, count(*) AS n
          FROM colas
         WHERE completed_date >= current_date - 14
           AND form_view IS NOT NULL AND form_scraped_on IS NULL
         GROUP BY 1, 2, 3 ORDER BY 1 DESC, 4 DESC
        """
    ):
        print("  ", dict(r))
    r = (await fetch_all(
        """--sql
        SELECT count(*) AS recent_days_rows,
               count(*) FILTER (WHERE form_scraped_on IS NULL) AS unread,
               count(*) FILTER (WHERE form_view IS NOT NULL AND form_scraped_on IS NULL) AS cleared
          FROM colas
         WHERE completed_date >= current_date - 14
        """
    ))[0]
    print("last 14 completed days:", dict(r))
    await close_pool()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
