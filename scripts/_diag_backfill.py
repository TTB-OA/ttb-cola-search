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
    await close_pool()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
