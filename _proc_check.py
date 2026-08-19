import json

import psycopg
from psycopg.rows import dict_row

from src.api.config import get_settings
from src.api.db import _base_kwargs
from src.api.mappers import DETAIL_COLUMNS, SEARCH_TABLE, detail_from_rows

s = get_settings()
kw = _base_kwargs(s)
kw.pop("row_factory", None)
kw.pop("autocommit", None)
pw = s.postgres_password
if pw:
    kw["password"] = pw
else:
    from azure.identity import DefaultAzureCredential

    kw["password"] = DefaultAzureCredential().get_token(
        "https://ossrdbms-aad.database.windows.net/.default"
    ).token

with psycopg.connect(row_factory=dict_row, **kw) as conn, conn.cursor() as cur:
    cur.execute('SET search_path TO "' + s.postgres_schema + '", public')
    ids = []
    for predicate in (
        "detail_scraped_on IS NOT NULL AND image_vector_count > 0 AND analysis_item_count > 0",
        "detail_scraped_on IS NULL",
        "detail_scraped_on IS NOT NULL AND image_success_count > 0 AND analysis_count = 0",
    ):
        cur.execute(
            f"SELECT cola_id FROM {SEARCH_TABLE} WHERE {predicate} LIMIT 1"  # noqa: S608
        )
        row = cur.fetchone()
        print(predicate, "->", row["cola_id"] if row else None)
        if row:
            ids.append(row["cola_id"])

    print()
    for cid in ids:
        cur.execute(f"SELECT {DETAIL_COLUMNS} FROM {SEARCH_TABLE} WHERE cola_id = %s", [cid])
        d = detail_from_rows(cur.fetchone(), [], [])
        print(cid, json.dumps(d.model_dump(by_alias=True)["processing"]))
