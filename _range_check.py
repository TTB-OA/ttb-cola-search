"""Scratch: exercise the coverage complete-range SQL against the real database."""
import json
import time

import psycopg
from psycopg.rows import dict_row

from src.api.config import get_settings
from src.api.db import _base_kwargs
from src.api.mappers import summary_from_row
from src.api.routers.coverage import _COMPLETE_RANGE_SQL

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
    t0 = time.perf_counter()
    cur.execute(_COMPLETE_RANGE_SQL)
    rows = cur.fetchall()
    print(f"{len(rows)} rows in {time.perf_counter() - t0:.2f}s")
    for row in rows:
        which = []
        if row["cola_id"] == row["earliest_id"]:
            which.append("earliest")
        if row["cola_id"] == row["latest_id"]:
            which.append("latest")
        summary = summary_from_row(row)
        print(
            "/".join(which),
            json.dumps(summary.model_dump(by_alias=True, mode="json"), indent=2),
        )
