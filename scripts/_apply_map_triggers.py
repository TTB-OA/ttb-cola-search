"""One-off: apply only the cola_map_source_cola triggers from the baseline to a schema.

The full baseline locks every view and trigger-bearing table, and API map reads
deadlock against it. These two statements touch only colas. Follow with
`schema_migrate --stamp-only` once the rest of the baseline is known to match.

Run from inside pipeline/: uv run python ../scripts/_apply_map_triggers.py [schema]
"""
import sys

from cola.core.pcr_baseline import PCR_BASELINE_SQL
from cola.core.pcr_env import get_conn
from cola.pipeline.schema_migrate import render

SCHEMA = sys.argv[1] if len(sys.argv) > 1 else "pcr-prod"

statements = [
    line for line in render(PCR_BASELINE_SQL, SCHEMA).splitlines()
    if line.startswith("CREATE OR REPLACE TRIGGER cola_map_source_cola_")
]
assert len(statements) == 2, statements

conn = get_conn()
try:
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('lock_timeout', '10s', true);")
        for statement in statements:
            cur.execute(statement)
        cur.execute(
            """--sql
            SELECT t.tgname, pg_get_triggerdef(t.oid)
              FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
             WHERE c.relnamespace = %s::regnamespace AND c.relname = 'colas'
               AND t.tgname LIKE 'cola_map_source_cola%%'
            """,
            (f'"{SCHEMA}"',),
        )
        for name, ddl in cur.fetchall():
            print(name, "::", ddl[:160])
    conn.commit()
    print(f"applied to {SCHEMA}")
finally:
    conn.close()
