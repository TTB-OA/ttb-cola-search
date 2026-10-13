"""One-off: prove the narrowed colas->map trigger on pcr-dev, inside a rolled-back transaction.

Run from inside pipeline/: uv run python ../scripts/_diag_map_trigger.py
"""
from cola.core.pcr_baseline import PCR_BASELINE_SQL
from cola.core.pcr_env import get_conn
from cola.pipeline.schema_migrate import render

SCHEMA = "pcr-dev"
S = f'"{SCHEMA}"'

conn = get_conn()
try:
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('lock_timeout', '20s', true);")
        cur.execute(render(PCR_BASELINE_SQL, SCHEMA))
        cur.execute(f"SELECT cola_id FROM {S}.colas WHERE application_date IS NOT NULL LIMIT 1")
        (cola_id,) = cur.fetchone()

        def queued():
            cur.execute(f"SELECT count(*) FROM {S}.cola_map_dirty WHERE cola_id = %s", (cola_id,))
            return cur.fetchone()[0]

        cur.execute(f"DELETE FROM {S}.cola_map_dirty WHERE cola_id = %s", (cola_id,))
        cur.execute(f"UPDATE {S}.colas SET printed_name = 'trigger probe', form_scraped_on = now() WHERE cola_id = %s", (cola_id,))
        print("form-only update queues map:", queued())
        cur.execute(f"UPDATE {S}.colas SET application_date = application_date WHERE cola_id = %s", (cola_id,))
        print("no-op update of a map column queues map:", queued())
        cur.execute(f"UPDATE {S}.colas SET application_date = application_date + 1 WHERE cola_id = %s", (cola_id,))
        print("real change to a map column queues map:", queued())
finally:
    conn.rollback()
    conn.close()
    print("rolled back")
