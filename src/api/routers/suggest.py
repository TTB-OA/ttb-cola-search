"""Typeahead suggestions for the advanced search form."""
from __future__ import annotations

from fastapi import APIRouter, Query

from ..db import fetch_all
from ..models import PermitSuggestion

router = APIRouter(tags=["suggest"])

# Below this the term matches most of the table and the list is useless.
MIN_TERM_LENGTH = 2

# cola_permits is ~90k rows over ~10k distinct permits, so the roll-up is cheap
# even when the name branch cannot use the permit_id index. Ordering by how many
# COLAs a permit carries puts the permit the user is likely after at the top.
_PERMIT_SUGGEST_SQL = """--sql
SELECT permit_id,
       max(permit_name)      AS permit_name,
       max(permit_city_addr) AS city,
       max(permit_state_addr) AS state,
       count(*)              AS cola_count
  FROM cola_permits
 WHERE permit_id LIKE %s OR permit_name ILIKE %s
 GROUP BY permit_id
 ORDER BY count(*) DESC, permit_id
 LIMIT %s
"""


def _like_literal(term: str) -> str:
    """Neutralise LIKE wildcards so a typed `%` or `_` matches itself."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@router.get("/suggest/permits", response_model=list[PermitSuggestion])
async def suggest_permits(
    q: str = Query(
        title="Permit term",
        description=(
            "Permit/plant number prefix, or any part of the permit holder name. "
            f"Terms shorter than {MIN_TERM_LENGTH} characters return no suggestions."
        ),
        examples=["BWN-CA", "cedar"],
    ),
    limit: int = Query(default=8, ge=1, le=25),
) -> list[PermitSuggestion]:
    term = (q or "").strip()
    if len(term) < MIN_TERM_LENGTH:
        return []

    escaped = _like_literal(term)
    rows = await fetch_all(
        _PERMIT_SUGGEST_SQL,
        # Permit ids are uppercase upstream; names are matched case-insensitively.
        [f"{escaped.upper()}%", f"%{escaped}%", limit],
    )
    return [
        PermitSuggestion(
            permit_id=row["permit_id"],
            name=row.get("permit_name"),
            city=row.get("city"),
            state=row.get("state"),
            cola_count=int(row["cola_count"]),
        )
        for row in rows
    ]
