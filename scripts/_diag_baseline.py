"""One-off: execute the rendered baseline against a schema and ROLL BACK.

Validates that the DDL and the CREATE OR REPLACE VIEW statements are accepted
(column names/types/order) without stamping or changing anything.
Run from inside pipeline/: uv run python ../scripts/_diag_baseline.py [schema]
"""
import sys

from cola.core.pcr_baseline import PCR_BASELINE_SQL
from cola.core.pcr_env import get_conn
from cola.pipeline.schema_migrate import render

schema = sys.argv[1] if len(sys.argv) > 1 else "pcr-dev"
conn = get_conn()
try:
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('lock_timeout', '20s', true);")
        cur.execute(render(PCR_BASELINE_SQL, schema))
        cur.execute(
            """--sql
            SELECT column_name, data_type
              FROM information_schema.columns
             WHERE table_schema = %s AND table_name = 'vw_colas'
               AND column_name IN ('appellation','applicant_phone','printed_name',
                                   'container_text','ttb_signed','form_view',
                                   'form_scraped_on','search_tsv')
             ORDER BY ordinal_position
            """,
            (schema,),
        )
        for row in cur.fetchall():
            print("  vw_colas:", row)
        cur.execute(
            """--sql
            SELECT count(*) FROM information_schema.columns
             WHERE table_schema = %s AND table_name = 'cola_search'
               AND column_name IN ('applicant_phone','printed_name','container_text',
                                   'ttb_signed','form_view','form_scraped_on','wine_vintage')
            """,
            (schema,),
        )
        print("  cola_search new columns present:", cur.fetchone()[0], "/ 7")
    print(f"[OK] baseline executed against {schema}; rolling back")
finally:
    conn.rollback()
    conn.close()
