"""One-off: add colas/cola_search net_contents + alcohol_content and re-create the
two views that expose them, each in its own short transaction.

The full baseline deadlocks against API map reads, so apply just these and
follow with `schema_migrate --stamp-only --skip-concurrent-indexes`.

Run from inside pipeline/: uv run python ../scripts/_apply_net_contents.py [schema]
"""
import re
import sys

from cola.core.pcr_baseline import PCR_BASELINE_SQL
from cola.core.pcr_env import get_conn
from cola.pipeline.schema_migrate import quote_schema, render

SCHEMA = sys.argv[1] if len(sys.argv) > 1 else "pcr-prod"
rendered = render(PCR_BASELINE_SQL, SCHEMA)
q = quote_schema(SCHEMA)


def view(name: str) -> str:
    match = re.search(
        rf"^CREATE OR REPLACE VIEW {re.escape(q)}\.{name} AS\n.*?;$",
        rendered, re.DOTALL | re.MULTILINE,
    )
    assert match, name
    assert "c.alcohol_content" in match.group(0), name
    return match.group(0)


statements = [
    f"ALTER TABLE {q}.colas ADD COLUMN IF NOT EXISTS net_contents character varying(64),"
    " ADD COLUMN IF NOT EXISTS alcohol_content character varying(32);",
    f"ALTER TABLE {q}.cola_search ADD COLUMN IF NOT EXISTS net_contents character varying(64),"
    " ADD COLUMN IF NOT EXISTS alcohol_content character varying(32);",
    view("v_colas_labeled"),
    view("vw_colas"),
]

conn = get_conn()
try:
    for statement in statements:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('lock_timeout', '10s', true);")
            cur.execute(statement)
        conn.commit()
        print("ok:", statement.splitlines()[0][:100])
    with conn.cursor() as cur:
        cur.execute(
            """--sql
            SELECT table_name, column_name FROM information_schema.columns
             WHERE table_schema = %s AND column_name IN ('net_contents', 'alcohol_content')
             ORDER BY 1, 2
            """,
            (SCHEMA,),
        )
        for row in cur.fetchall():
            print(row)
finally:
    conn.close()
