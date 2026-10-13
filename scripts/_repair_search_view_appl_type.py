"""One-off repair: restore application_type that a search-view read overwrote.

Paper COLAs got application_type from scan_extract (fill-only). The form-field
backfill then wrote the search view's bare "LABEL APPROVAL" over it. The scan
reading is kept in cola_scan_extraction.metadata, so the first one that
filled the column is restored. Rows where the scan had no value keep the
search-view value, which filled a blank.

Run from inside pipeline/: uv run python ../scripts/_repair_search_view_appl_type.py [--apply]
"""
import sys

from cola.core.pcr_env import get_conn

SCHEMA = "pcr-prod"
APPLY = "--apply" in sys.argv

SELECT = """--sql
    WITH first_scan AS (
        SELECT DISTINCT ON (x.cola_id)
               x.cola_id, x.metadata -> 'form_flags' ->> 'application_type' AS scan_appl_type
          FROM "{s}".cola_scan_extraction x
         WHERE x.metadata -> 'form_flags' ->> 'application_type' IS NOT NULL
         ORDER BY x.cola_id, x.completed_on
    )
    SELECT c.cola_id, c.application_type AS now_value, f.scan_appl_type
      FROM "{s}".colas c
      JOIN first_scan f USING (cola_id)
     WHERE c.form_view = 'search'
       AND c.application_type IS DISTINCT FROM f.scan_appl_type
""".format(s=SCHEMA)

conn = get_conn()
try:
    with conn.cursor() as cur:
        cur.execute(SELECT)
        rows = cur.fetchall()
    print(f"rows to restore: {len(rows):,}")
    by_pair: dict[tuple, int] = {}
    for _, now_value, scan_value in rows:
        by_pair[(now_value, scan_value)] = by_pair.get((now_value, scan_value), 0) + 1
    for (now_value, scan_value), n in sorted(by_pair.items(), key=lambda kv: -kv[1])[:8]:
        print(f"  {n:>6,}  {now_value!r} -> {scan_value!r}")

    if APPLY and rows:
        with conn.cursor() as cur:
            cur.execute(
                """--sql
                UPDATE "{s}".colas c
                   SET application_type = v.scan_appl_type
                  FROM unnest(%s::text[], %s::text[]) AS v(cola_id, scan_appl_type)
                 WHERE c.cola_id = v.cola_id
                """.format(s=SCHEMA),
                ([r[0] for r in rows], [r[2] for r in rows]),
            )
            print(f"updated: {cur.rowcount:,}")
        conn.commit()
    elif rows:
        print("dry run; pass --apply to write")
finally:
    conn.rollback()
    conn.close()
