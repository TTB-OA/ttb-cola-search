"""Paper-scan extraction ledger: models, statuses, and which rows predate the new-field prompt.

Run from inside pipeline/: uv run python ../scripts/_diag_scan_ledger.py
"""
from cola.core.pcr_env import get_conn

conn = get_conn()
with conn.cursor() as cur:
    cur.execute(
        """--sql
        SELECT extraction_model, extraction_status,
               count(*) AS sheets,
               count(*) FILTER (WHERE metadata->'form_flags' ? 'printed_name') AS named,
               count(*) FILTER (WHERE metadata ? 'fields_read') AS fields_read,
               min(completed_on)::date, max(completed_on)::date
          FROM "pcr-prod".cola_scan_extraction
         GROUP BY 1, 2 ORDER BY 1, 2
        """
    )
    for row in cur.fetchall():
        print(*row)
    cur.execute(
        """--sql
        SELECT completed_on::date, count(*),
               count(*) FILTER (WHERE metadata->'form_flags' ? 'printed_name')
          FROM "pcr-prod".cola_scan_extraction
         WHERE completed_on >= '2026-10-05'
         GROUP BY 1 ORDER BY 1
        """
    )
    print("by day since 10-05:")
    for row in cur.fetchall():
        print(*row)
    cur.execute(
        """--sql
        SELECT count(*), count(DISTINCT cola_id)
          FROM "pcr-prod".cola_scan_extraction
         WHERE extraction_status IN ('SUCCESS', 'NONE')
           AND NOT (metadata->'form_flags' ? 'printed_name')
        """
    )
    print("success/none sheets lacking printed_name:", cur.fetchone())
conn.close()
