"""One-off: are the form-filter indexes on cola_search built and valid?"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

load_dotenv()
from api.db import close_pool, fetch_all, open_pool  # noqa: E402

NAMES = [
    "cola_search_application_date_idx",
    "cola_search_appellation_trgm_idx",
    "cola_search_formula_upper_idx",
]


async def main() -> None:
    await open_pool()
    rows = await fetch_all(
        """--sql
        SELECT c.relname, x.indisvalid, pg_size_pretty(pg_relation_size(c.oid)) AS size
          FROM pg_class c
          JOIN pg_index x ON x.indexrelid = c.oid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = current_schema() AND c.relname = ANY(%s)
        """,
        [NAMES],
    )
    found = {r["relname"]: r for r in rows}
    for name in NAMES:
        r = found.get(name)
        print(f"  {name:36} " + (f"valid={r['indisvalid']} size={r['size']}" if r else "MISSING"))
    await close_pool()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
