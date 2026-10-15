"""Token totals for scan_fields_batch readings so far, by pass.

Run from inside pipeline/: uv run python ../scripts/_diag_scan_fields_tokens.py
"""
from cola.core.pcr_env import get_conn

conn = get_conn()
with conn.cursor() as cur:
    cur.execute(
        """--sql
        SELECT metadata->'fields_read'->>'thinking_level' AS pass,
               count(*),
               avg((metadata->'fields_read'->'usage'->>'prompt')::int)::int,
               avg((metadata->'fields_read'->'usage'->>'output')::int)::int,
               avg(COALESCE((metadata->'fields_read'->'usage'->>'thinking')::int, 0))::int,
               count(*) FILTER (WHERE metadata->'fields_read'->'form_flags' ? 'printed_name')
          FROM "pcr-prod".cola_scan_extraction
         WHERE metadata ? 'fields_read'
         GROUP BY 1
        """
    )
    print("pass sheets avg_prompt avg_output avg_thinking with_name")
    for row in cur.fetchall():
        print(*row)
conn.close()
