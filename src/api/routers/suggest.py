"""Typeahead suggestions for the advanced search form."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from ..db import fetch_all
from ..mappers import PERMIT_TABLE
from ..models import PermitSuggestion

router = APIRouter(tags=["suggest"])

# Below this the term matches most of the table and the list is useless.
MIN_TERM_LENGTH = 2
# pg_trgm needs three characters to form a trigram, so a shorter term cannot use
# the names_blob index and would degrade into a scan. Below this the term is
# matched as an id prefix only, which the btree still serves.
MIN_NAME_TERM_LENGTH = 3

# One row per permit, so this is a bounded index lookup rather than the
# per-keystroke roll-up over cola_permits it replaces. Ordering by how many
# COLAs a permit carries puts the permit the user is likely after at the top.
_ID_MATCH = "permit_id LIKE %s"
# names_blob carries every name the permit has traded under, not just the
# current one, so a search for a former business name still finds it.
_ID_OR_NAME_MATCH = f"{_ID_MATCH} OR names_blob ILIKE %s"

_PERMIT_SUGGEST_SQL = """--sql
SELECT permit_id,
       permit_name,
       permit_city_addr  AS city,
       permit_state_addr AS state,
       cola_count
  FROM {table}
 WHERE {match}
 ORDER BY cola_count DESC, permit_id
 LIMIT %s
"""

_SQL_BY_ID = _PERMIT_SUGGEST_SQL.format(table=PERMIT_TABLE, match=_ID_MATCH)
_SQL_BY_ID_OR_NAME = _PERMIT_SUGGEST_SQL.format(
    table=PERMIT_TABLE, match=_ID_OR_NAME_MATCH
)


def _like_literal(term: str) -> str:
    """Neutralise LIKE wildcards so a typed `%` or `_` matches itself."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/suggest/permits", response_model=list[PermitSuggestion])
async def suggest_permits(
    q: str = Query(
        title="Permit term",
        description=(
            "Permit/plant number prefix, or any part of a permit holder name the "
            "permit has traded under. Terms shorter than "
            f"{MIN_TERM_LENGTH} characters return no suggestions; shorter than "
            f"{MIN_NAME_TERM_LENGTH} are matched as a permit number only."
        ),
        examples=["BWN-CA", "cedar"],
    ),
    limit: int = Query(default=8, ge=1, le=25),
) -> list[PermitSuggestion]:
    term = (q or "").strip()
    if len(term) < MIN_TERM_LENGTH:
        return []

    escaped = _like_literal(term)
    # Permit ids are uppercase upstream; names are matched case-insensitively.
    params: list[Any] = [f"{escaped.upper()}%"]
    sql = _SQL_BY_ID
    if len(term) >= MIN_NAME_TERM_LENGTH:
        sql = _SQL_BY_ID_OR_NAME
        params.append(f"%{escaped}%")
    params.append(limit)

    rows = await fetch_all(sql, params)
    return [
        PermitSuggestion(
            permit_id=row["permit_id"],
            # Null until at least one of the permit's COLAs is detail-filled;
            # the UI falls back to the id.
            name=row.get("permit_name"),
            city=row.get("city"),
            state=row.get("state"),
            cola_count=int(row["cola_count"]),
        )
        for row in rows
    ]
