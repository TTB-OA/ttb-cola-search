"""One-off: why is the backward scan_extract leg idle? Ledger state vs unread form scans."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

load_dotenv()
from api.db import close_pool, fetch_all, open_pool  # noqa: E402


async def main() -> None:
    await open_pool()
    cols = [r["column_name"] for r in await fetch_all(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'pipeline_day_status' ORDER BY ordinal_position"
    )]
    print("pipeline_day_status columns:", cols)
    status_col = "status" if "status" in cols else cols[2]
    for r in await fetch_all(
        f"""--sql
        SELECT {status_col} AS status, count(*) AS days,
               min(business_date) AS first_day, max(business_date) AS last_day
          FROM pipeline_day_status
         WHERE component = 'scan_extract'
         GROUP BY 1 ORDER BY 1
        """
    ):
        print("  ", dict(r))
    r = (await fetch_all(
        """--sql
        SELECT 50 * count(*) AS form_scans,
               50 * count(*) FILTER (WHERE NOT EXISTS (
                   SELECT 1 FROM cola_scan_extraction x
                    WHERE x.cola_id = i.cola_id AND x.file_name = i.file_name)) AS unread
          FROM cola_images i TABLESAMPLE SYSTEM (2)
         WHERE i.image_role = 'form_scan' AND i.blob_name IS NOT NULL
        """
    ))[0]
    print("form scans (2% sample x50):", dict(r))
    r = (await fetch_all(
        "SELECT max(completed_on) AS last_scan, count(*) FILTER (WHERE completed_on >= now() - interval '7 days') AS last_7d "
        "FROM cola_scan_extraction"
    ))[0]
    print("scan reads:", dict(r))
    await close_pool()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
