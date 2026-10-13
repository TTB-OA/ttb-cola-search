"""One-off: which days hold the unread paper scans, and what a repair pass would read there.

Run from inside pipeline/: uv run python ../scripts/_diag_scan_catchup.py [--reopen]
--reopen puts those scan_extract days back to pending so `scan_extract --mode repair`
reads them; downstream OCR/embedding reopen via stale_upstream_days.
"""
import sys

from cola.core import incremental
from cola.core.pcr_env import get_conn
from cola.core.pcr_schema import COMPONENT_SCAN_EXTRACT
from cola.pipeline.scan_extract import default_scan_model, query_uncovered_scans

SCHEMA = "pcr-prod"
S = f'"{SCHEMA}"'
MODEL = default_scan_model()

conn = get_conn()
try:
    with conn.cursor() as cur:
        cur.execute(f"""--sql
            SELECT extraction_model, count(*) FROM {S}.cola_scan_extraction GROUP BY 1 ORDER BY 2 DESC
        """)
        print("extraction rows by model:", cur.fetchall(), " current default:", MODEL)

        cur.execute(f"""--sql
            SELECT c.completed_date, count(*)
              FROM {S}.cola_images i JOIN {S}.colas c USING (cola_id)
             WHERE i.image_role = 'form_scan' AND i.blob_name IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM {S}.cola_scan_extraction x
                                WHERE x.cola_id = i.cola_id AND x.file_name = i.file_name)
             GROUP BY 1 ORDER BY 1
        """)
        days = cur.fetchall()

        cur.execute(f"""--sql
            SELECT business_date, status FROM {S}.pipeline_day_status
             WHERE component = %s AND business_date = ANY(%s)
        """, (COMPONENT_SCAN_EXTRACT, [d for d, _ in days]))
        status = dict(cur.fetchall())

    total_unread = total_repair = 0
    print(f"\n{len(days)} days hold never-read scans:")
    for day, unread in days:
        would_read = len(query_uncovered_scans(conn, SCHEMA, day, MODEL))
        total_unread += unread
        total_repair += would_read
        print(f"  {day}  status={status.get(day)}  unread={unread}  repair would read={would_read}")
    print(f"total unread={total_unread:,}  repair would read={total_repair:,}")

    if "--reopen" in sys.argv:
        n = incremental.reopen_days(
            conn, SCHEMA, COMPONENT_SCAN_EXTRACT, [d for d, _ in days],
            reason="never-read form scans on a settled day",
        )
        print(f"reopened {n} scan_extract days")
finally:
    conn.rollback()
    conn.close()
