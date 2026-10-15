"""Which scan extractions already carry the new written fields (ground truth candidates)?

Run from inside pipeline/: uv run python ../scripts/_diag_scan_truth.py
"""
from cola.core.pcr_env import get_conn

conn = get_conn()
with conn.cursor() as cur:
    cur.execute(
        """--sql
        SELECT date_trunc('day', e.completed_on)::date AS read_on,
               e.extraction_model,
               e.metadata->>'thinking_level' AS thinking,
               count(*) AS sheets,
               count(*) FILTER (WHERE e.metadata->'form_flags' ? 'printed_name') AS named,
               count(*) FILTER (WHERE e.metadata->'form_flags' ? 'container_text') AS item15,
               min(c.completed_date), max(c.completed_date)
          FROM "pcr-prod".cola_scan_extraction e
          JOIN "pcr-prod".colas c USING (cola_id)
         WHERE e.completed_on >= '2026-10-07'
         GROUP BY 1, 2, 3 ORDER BY 1
        """
    )
    for row in cur.fetchall():
        print(*row)
conn.close()
