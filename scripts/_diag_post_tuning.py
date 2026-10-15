"""One-off: post-tuning check -- map queue, OCR throughput, scan catch-up.

Run from inside pipeline/: uv run python ../scripts/_diag_post_tuning.py
"""
from cola.core.pcr_env import get_conn

S = '"pcr-prod"'

conn = get_conn()
try:
    with conn.cursor() as cur:
        cur.execute(f"""--sql
            SELECT (SELECT count(*) FROM {S}.cola_map_dirty),
                   (SELECT max(_loaded_at) FROM {S}.cola_map_search),
                   (SELECT count(*) FROM {S}.cola_map_search WHERE _loaded_at >= now() - interval '24 hours')
        """)
        dirty, last_loaded, loaded_24h = cur.fetchone()
        print(f"map: queue={dirty:,}  rows written last 24h={loaded_24h:,}  last write={last_loaded}")

        cur.execute(f"""--sql
            SELECT date_trunc('hour', analysis_completed_on) AS hour, count(*) AS images
              FROM {S}.cola_image_analysis
             WHERE analysis_completed_on >= now() - interval '36 hours'
             GROUP BY 1 ORDER BY 1
        """)
        rows = cur.fetchall()
        print("\nOCR images completed per hour (last 36h):")
        for hour, n in rows:
            print(f"  {hour:%m-%d %H:00}Z  {n:>6,}")

        cur.execute(f"""--sql
            SELECT count(*) FILTER (WHERE NOT EXISTS (
                       SELECT 1 FROM {S}.cola_scan_extraction x
                        WHERE x.cola_id = i.cola_id AND x.file_name = i.file_name)) AS unread
              FROM {S}.cola_images i
             WHERE i.image_role = 'form_scan' AND i.blob_name IS NOT NULL
        """)
        print(f"\nform scans never read by Gemini: {cur.fetchone()[0]:,}")
        cur.execute(f"""--sql
            SELECT count(*),
                   count(*) FILTER (WHERE metadata -> 'form_flags' ->> 'printed_name' IS NOT NULL),
                   count(*) FILTER (WHERE metadata -> 'form_flags' ->> 'applicant_phone' IS NOT NULL),
                   count(*) FILTER (WHERE metadata -> 'form_flags' ->> 'formula_num' IS NOT NULL),
                   count(*) FILTER (WHERE (metadata -> 'form_flags' ->> 'ttb_signed')::boolean)
              FROM {S}.cola_scan_extraction
             WHERE completed_on >= '2026-10-12 23:00+00'
        """)
        n, name, phone, formula, signed = cur.fetchone()
        print(f"scans read since catch-up: {n:,}  printed_name={name:,} phone={phone:,} "
              f"formula={formula:,} ttb_signed={signed:,}")
finally:
    conn.close()
