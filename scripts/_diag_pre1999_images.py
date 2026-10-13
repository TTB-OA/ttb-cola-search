"""One-off: what the image pass recorded for pre-1999 COLAs, and a sample to re-probe.

Run from inside pipeline/: uv run python ../scripts/_diag_pre1999_images.py
"""
from cola.core.pcr_env import get_conn

S = '"pcr-prod"'

conn = get_conn()
try:
    with conn.cursor() as cur:
        cur.execute(f"""--sql
            SELECT i.download_status, i.image_role, count(DISTINCT i.cola_id) AS colas
              FROM {S}.cola_images i JOIN {S}.colas c USING (cola_id)
             WHERE c.completed_date < '1999-01-01'
             GROUP BY 1, 2 ORDER BY 3 DESC
        """)
        print("pre-1999 image outcomes (per COLA):")
        for row in cur.fetchall():
            print("  ", row)

        cur.execute(f"""--sql
            SELECT count(*) FROM {S}.colas c
             WHERE c.completed_date < '1999-01-01'
               AND NOT EXISTS (SELECT 1 FROM {S}.cola_images i WHERE i.cola_id = c.cola_id)
        """)
        print("pre-1999 COLAs with no image row at all:", cur.fetchone()[0])

        cur.execute(f"""--sql
            SELECT c.cola_id, c.completed_date, c.received_code, i.file_name, i.image_role
              FROM {S}.colas c JOIN {S}.cola_images i USING (cola_id)
             WHERE c.completed_date < '1999-01-01' AND i.blob_name IS NOT NULL
             ORDER BY c.completed_date DESC LIMIT 25
        """)
        print("\npre-1999 COLAs that do have a stored image:")
        for row in cur.fetchall():
            print("  ", row)

        cur.execute(f"""--sql
            SELECT extract(year FROM c.completed_date)::int AS yr, c.cola_id, c.received_code
              FROM {S}.colas c TABLESAMPLE SYSTEM (0.2)
             WHERE c.completed_date < '1999-01-01'
               AND c.image_count_to_parse IS DISTINCT FROM 1
             ORDER BY random() LIMIT 12
        """)
        print("\nrandom pre-1999 sample to re-probe:")
        for row in cur.fetchall():
            print("  ", row)
finally:
    conn.close()
