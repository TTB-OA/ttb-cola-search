"""One-off: progress of a form-field backfill run on prod (2% sample, scaled).

DIAG_LAUNCHED (UTC launch time), DIAG_FROM / DIAG_TO (completed_date range,
end exclusive) select the run. Exact counts over a multi-year range exceed the
API pool's 15s statement_timeout, hence the sample.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

load_dotenv()
from api.db import close_pool, fetch_all, open_pool  # noqa: E402

LAUNCHED = os.environ.get("DIAG_LAUNCHED", "2026-10-09 19:32:22+00")
DATE_FROM = os.environ.get("DIAG_FROM", "2020-01-01")
DATE_TO = os.environ.get("DIAG_TO", "2025-01-01")


async def main() -> None:
    await open_pool()
    r = (await fetch_all(
        """--sql
        SELECT 50 * count(*) FILTER (WHERE c.received_code = 'ES') AS es_total,
               50 * count(*) FILTER (WHERE c.received_code = 'ES'
                                       AND c.image_count_to_parse > 0
                                       AND c.form_scraped_on IS NULL) AS es_imaged_unread,
               50 * count(*) FILTER (WHERE c.form_scraped_on >= %s::timestamptz) AS done_this_run,
               50 * count(*) FILTER (WHERE c.form_scraped_on >= now() - interval '10 minutes') AS last_10m,
               now() AS now
          FROM colas c TABLESAMPLE SYSTEM (2)
         WHERE c.completed_date >= %s AND c.completed_date < %s
        """,
        [LAUNCHED, DATE_FROM, DATE_TO],
    ))[0]
    rate = r["last_10m"] / 600
    eta_h = r["es_imaged_unread"] / rate / 3600 if rate else None
    print(f"range {DATE_FROM}..{DATE_TO} (estimates, +/- a few %)")
    print(f"  done this run   ~{r['done_this_run']:,}")
    print(f"  remaining       ~{r['es_imaged_unread']:,}  (e-filed, imaged, unread)")
    print(f"  last 10 min     ~{r['last_10m']:,}  (~{rate:.1f}/s)"
          + (f", ETA ~{eta_h:.1f} h" if eta_h else ", not progressing"))
    q = (await fetch_all("SELECT count(*) AS n FROM cola_search_dirty"))[0]
    print(f"  dirty queue     {q['n']:,}")
    await close_pool()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
