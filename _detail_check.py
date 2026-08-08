import psycopg
from psycopg.rows import dict_row
from src.api.config import get_settings
from src.api.db import _base_kwargs
from src.api.mappers import DETAIL_COLUMNS, SEARCH_TABLE, image_display_order_sql, visual_interest_join_sql

CID = 26050001000402
s = get_settings()
kw = _base_kwargs(s)
kw.pop("row_factory", None); kw.pop("autocommit", None)
pw = s.postgres_password
if pw:
    kw["password"] = pw
else:
    from azure.identity import DefaultAzureCredential
    kw["password"] = DefaultAzureCredential().get_token("https://ossrdbms-aad.database.windows.net/.default").token

with psycopg.connect(row_factory=dict_row, **kw) as conn, conn.cursor() as cur:
    cur.execute('SET search_path TO "' + s.postgres_schema + '", public')
    cur.execute(f"SELECT {DETAIL_COLUMNS} FROM {SEARCH_TABLE} WHERE cola_id = %s", [CID])
    print("base:", "found" if cur.fetchone() else "MISSING")
    sql = (
        "SELECT ci.cola_id, ci.file_name, ci.img_type, vi.visual_interest_score, vi.visual_interest_rank "
        "FROM cola_images ci "
        f"{visual_interest_join_sql('ci')} "
        "WHERE ci.cola_id = %s "
        f"ORDER BY {image_display_order_sql('ci')}"
    )
    cur.execute(sql, [CID])
    rows = cur.fetchall()
    print("images:", len(rows))
    for r in rows:
        print("  ", r["file_name"], "|", r["img_type"], "| score=", r["visual_interest_score"])
