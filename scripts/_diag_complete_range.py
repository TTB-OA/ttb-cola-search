"""One-off: can the API role read cola_scan_extraction, and how fast is the new complete-range SQL?"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

load_dotenv()
from api.db import close_pool, fetch_all, open_pool  # noqa: E402
from api.routers.coverage import _COMPLETE_RANGE_SQL  # noqa: E402


async def main() -> None:
    await open_pool()
    print(await fetch_all("SELECT extraction_status, cola_id FROM cola_scan_extraction LIMIT 1"))
    t = time.perf_counter()
    rows = await fetch_all(_COMPLETE_RANGE_SQL, ["2023-01-01", "2023-01-01"])
    print(f"complete range {time.perf_counter() - t:.2f}s", [(r["earliest_id"], r["latest_id"]) for r in rows][:1])
    await close_pool()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
