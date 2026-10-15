"""Spot-check sheets written by scan_fields_batch: the fields_read marker vs. what colas now holds.

Run from inside pipeline/: uv run python ../scripts/_diag_scan_fields_written.py [limit]
"""
import sys

from cola.core.pcr_env import get_conn

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 20

conn = get_conn()
with conn.cursor() as cur:
    cur.execute(
        """--sql
        SELECT e.cola_id,
               e.metadata->'fields_read'->>'thinking_level',
               e.metadata->'fields_read'->'form_flags'->>'printed_name',
               c.printed_name, c.applicant_phone, c.appellation, c.ttb_signed,
               left(c.container_text, 40)
          FROM "pcr-prod".cola_scan_extraction e
          JOIN "pcr-prod".colas c USING (cola_id)
         WHERE e.metadata ? 'fields_read'
         ORDER BY e.metadata->'fields_read'->>'read_on' DESC
         LIMIT %s
        """,
        (LIMIT,),
    )
    for row in cur.fetchall():
        print(*row, sep=" | ")
    cur.execute(
        """--sql
        SELECT operation, count(*), sum(token_count)
          FROM "pcr-prod".api_usage
         WHERE operation = 'scan_fields_batch'
         GROUP BY 1
        """
    )
    print(cur.fetchall())
conn.close()
