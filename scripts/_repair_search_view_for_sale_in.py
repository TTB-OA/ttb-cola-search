"""One-off repair: restore for_sale_in that a search-view read nulled.

Only exemption certificates carry it, and the TTB detail API is the source.
Re-fetches /colas/{id} for search-view rows that had an API detail read and
are exemptions, and writes forSaleIn back where colas.for_sale_in is NULL.

Run from inside pipeline/: uv run python ../scripts/_repair_search_view_for_sale_in.py [--apply]
"""
import sys
import time

from cola.core import pcr_api
from cola.core.pcr_env import get_conn
from cola.core.scalars import clean_scalar

SCHEMA = "pcr-prod"
APPLY = "--apply" in sys.argv

conn = get_conn()
session = pcr_api.build_session()
try:
    with conn.cursor() as cur:
        cur.execute(
            f"""--sql
            SELECT cola_id FROM "{SCHEMA}".colas
             WHERE form_view = 'search' AND detail_scraped_on IS NOT NULL
               AND for_sale_in IS NULL
               AND (application_type LIKE '%%EXEMPTION%%' OR exemption_state IS NOT NULL)
             ORDER BY cola_id
            """
        )
        ids = [r[0] for r in cur.fetchall()]
    print(f"candidates: {len(ids):,}")

    restored = []
    for cola_id in ids:
        detail = None
        for candidate in pcr_api.detail_id_candidates(cola_id):
            detail, _ = pcr_api.get_json(session, f"{pcr_api.COLAS_PATH}/{candidate}")
            if detail:
                break
        value = clean_scalar((detail or {}).get("forSaleIn"))
        if value:
            restored.append((cola_id, value))
            print(f"  {cola_id}: {value!r}")
        time.sleep(pcr_api.REQUEST_DELAY_SEC)

    print(f"API has for_sale_in for {len(restored):,} of {len(ids):,}")
    if APPLY and restored:
        with conn.cursor() as cur:
            cur.execute(
                f"""--sql
                UPDATE "{SCHEMA}".colas c
                   SET for_sale_in = v.value
                  FROM unnest(%s::text[], %s::text[]) AS v(cola_id, value)
                 WHERE c.cola_id = v.cola_id AND c.for_sale_in IS NULL
                """,
                ([r[0] for r in restored], [r[1] for r in restored]),
            )
            print(f"updated: {cur.rowcount:,}")
        conn.commit()
finally:
    conn.rollback()
    conn.close()
