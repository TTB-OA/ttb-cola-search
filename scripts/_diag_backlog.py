"""One-off: form-field backfill backlog by completed year, e-filed vs paper, imaged or not."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

load_dotenv()
from api.db import close_pool, fetch_all, open_pool  # noqa: E402


async def main() -> None:
    await open_pool()
    # 2% sample scaled x50: exact counts over the join exceed the 15s timeout.
    rows = await fetch_all(
        """--sql
        SELECT extract(year FROM c.completed_date)::int AS yr,
               50 * count(*) AS unread,
               50 * count(*) FILTER (WHERE c.received_code = 'ES') AS es,
               50 * count(*) FILTER (WHERE c.received_code = 'ES' AND c.image_count_to_parse > 0) AS es_imaged,
               50 * count(*) FILTER (WHERE c.received_code <> 'ES' AND c.image_count_to_parse > 0) AS paper_imaged
          FROM colas c TABLESAMPLE SYSTEM (2)
         WHERE c.form_scraped_on IS NULL
           AND c.completed_date >= %s AND c.completed_date < %s
         GROUP BY 1 ORDER BY 1 DESC
        """,
        [os.environ.get("DIAG_FROM", "1995-01-01"), os.environ.get("DIAG_TO", "2025-01-01")],
    )
    tot = {"unread": 0, "es": 0, "es_imaged": 0, "paper_imaged": 0}
    for r in rows:
        print(f"  {r['yr']}  unread={r['unread']:>8,}  es={r['es']:>8,}  "
              f"es_imaged={r['es_imaged']:>8,}  paper_imaged={r['paper_imaged']:>8,}")
        for k in tot:
            tot[k] += r[k]
    print("  total", {k: f"{v:,}" for k, v in tot.items()})
    await close_pool()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
