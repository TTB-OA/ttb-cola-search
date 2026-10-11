"""One-off: exact backfill write rate from cola_search_dirty growth over DIAG_SECONDS."""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

load_dotenv()
from api.db import close_pool, fetch_all, open_pool  # noqa: E402

SECONDS = int(os.environ.get("DIAG_SECONDS", "120"))


async def main() -> None:
    await open_pool()
    sql = "SELECT count(*) AS n, max(marked_at) AS last FROM cola_search_dirty"
    a = (await fetch_all(sql))[0]
    t0 = time.monotonic()
    await asyncio.sleep(SECONDS)
    b = (await fetch_all(sql))[0]
    dt = time.monotonic() - t0
    grew = b["n"] - a["n"]
    print(f"dirty {a['n']:,} -> {b['n']:,} in {dt:.0f}s = {grew / dt:.2f}/s; last marked {b['last']}")
    if grew < 0:
        print("  (queue shrank: a materialize drain ran during the window; rerun)")
    await close_pool()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
