"""Fill rates among rows the old-form re-read has rewritten since it started.

Run from inside pipeline/: uv run python ../scripts/_diag_reread_progress.py [since-utc]
"""
import sys

from cola.core.pcr_env import get_conn

SINCE = sys.argv[1] if len(sys.argv) > 1 else "2026-10-14 22:22:29+00"

conn = get_conn()
with conn.cursor() as cur:
    cur.execute(
        """--sql
        SELECT extract(year FROM completed_date)::int AS yr,
               count(*) AS reread,
               round(100.0 * count(net_contents) / count(*), 1) AS net_pct,
               round(100.0 * count(alcohol_content) / count(*), 1) AS abv_pct,
               round(100.0 * count(wine_vintage) / count(*), 1) AS vintage_pct,
               round(100.0 * count(applicant_fax) / count(*), 1) AS fax_pct,
               round(100.0 * count(container_text) / count(*), 1) AS item15_pct,
               round(100.0 * count(*) FILTER (WHERE ttb_signed) / count(*), 1) AS signed_pct
          FROM "pcr-prod".colas
         WHERE form_scraped_on >= %s
           AND received_code = 'ES'
           AND completed_date < '2012-07-01'
         GROUP BY 1 ORDER BY 1
        """,
        (SINCE,),
    )
    print("yr reread net% abv% vintage% fax% item15% signed%")
    for row in cur.fetchall():
        print(*row)
conn.close()
