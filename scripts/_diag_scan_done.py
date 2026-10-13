"""One-off: is the paper-scan (Gemini) work finished, or stalled?

Run from inside pipeline/: uv run python ../scripts/_diag_scan_done.py
"""
from cola.core.pcr_env import get_conn

S = '"pcr-prod"'

conn = get_conn()
try:
    with conn.cursor() as cur:
        cur.execute(f"""--sql
            SELECT date_trunc('day', recorded_on)::date AS day, count(*) AS calls, sum(token_count) AS tokens
              FROM {S}.api_usage
             WHERE component = 'scan_extract' AND recorded_on >= now() - interval '21 days'
             GROUP BY 1 ORDER BY 1
        """)
        print("Gemini scan_extract calls per day (last 21 days):")
        for day, calls, tokens in cur.fetchall():
            print(f"  {day}  calls={calls:>7,}  tokens={tokens or 0:>13,}")

        cur.execute(f"""--sql
            SELECT count(*) AS sheets,
                   count(*) FILTER (WHERE NOT EXISTS (
                       SELECT 1 FROM {S}.cola_scan_extraction x
                        WHERE x.cola_id = i.cola_id AND x.file_name = i.file_name)) AS unread
              FROM {S}.cola_images i
             WHERE i.image_role = 'form_scan' AND i.blob_name IS NOT NULL
        """)
        sheets, unread = cur.fetchone()
        print(f"\nstored paper form scans: {sheets:,}; never read by Gemini: {unread:,}")

        cur.execute(f"""--sql
            SELECT extract(year FROM c.completed_date)::int AS yr, count(*)
              FROM {S}.cola_images i JOIN {S}.colas c USING (cola_id)
             WHERE i.image_role = 'form_scan' AND i.blob_name IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM {S}.cola_scan_extraction x
                                WHERE x.cola_id = i.cola_id AND x.file_name = i.file_name)
             GROUP BY 1 ORDER BY 2 DESC LIMIT 8
        """)
        rows = cur.fetchall()
        if rows:
            print("  unread by completed year:", ", ".join(f"{y}={n:,}" for y, n in rows))

        cur.execute(f"""--sql
            SELECT component, business_date, attempt_count, left(coalesce(last_error, ''), 120)
              FROM {S}.pipeline_day_status
             WHERE status = 'gave_up' AND component IN ('scan_extract', 'image_ingest')
             ORDER BY 1, 2
        """)
        print("\ngave_up days:")
        for row in cur.fetchall():
            print("  ", row)

        cur.execute(f"""--sql
            SELECT CASE WHEN c.completed_date < '1999-01-01' THEN 'pre-1999'
                        WHEN c.received_code = 'ES' THEN 'e-filed 1999+'
                        ELSE 'paper 1999+' END AS kind,
                   count(*) AS colas,
                   count(*) FILTER (WHERE c.image_count_to_parse > 0) AS with_images,
                   count(*) FILTER (WHERE c.image_count_to_parse = 0 OR c.image_count_to_parse IS NULL) AS without
              FROM {S}.colas c
             GROUP BY 1 ORDER BY 1
        """)
        print("\nimage coverage by kind:")
        for row in cur.fetchall():
            print("  ", row)
finally:
    conn.close()
