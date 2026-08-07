"""Health and readiness endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter

from ..config import get_settings
from ..db import fetch_one
from ..embedding import available_providers
from ..mappers import COVERAGE_TABLE, OCR_TABLE, SEARCH_TABLE

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

# Relations no request can be served without. A bare "SELECT 1" only proves the
# connection works: when search_path points at a schema that does not hold these
# it still succeeds while every real query fails with UndefinedTable, so resolve
# the names as well as the connection.
REQUIRED_RELATIONS: tuple[str, ...] = (SEARCH_TABLE, OCR_TABLE, COVERAGE_TABLE)

# to_regclass() resolves through search_path exactly as a query would, and is a
# catalog lookup rather than a scan, so this stays cheap enough for a probe.
_PROBE_SQL = """--sql
SELECT
    current_schema()               AS resolved_schema,
    current_setting('search_path') AS search_path,
    ARRAY(
        SELECT rel
        FROM unnest(%s::text[]) AS rel
        WHERE to_regclass(rel) IS NULL
    )                              AS missing_relations
"""


@router.get("/health")
async def health() -> dict[str, object]:
    settings = get_settings()
    connected = False
    resolved_schema: str | None = None
    search_path: str | None = None
    missing: list[str] = list(REQUIRED_RELATIONS)
    error: str | None = None

    try:
        row = await fetch_one(_PROBE_SQL, [list(REQUIRED_RELATIONS)]) or {}
    except Exception:  # noqa: BLE001 - health degrades, it never fails hard
        # Logged rather than returned: the endpoint is public, so it reports a
        # classification instead of the driver's message.
        logger.warning("health probe could not reach the database", exc_info=True)
        error = "connection_failed"
    else:
        connected = True
        resolved_schema = row.get("resolved_schema")
        search_path = row.get("search_path")
        missing = list(row.get("missing_relations") or [])
        if missing:
            error = "missing_relations"
            logger.warning(
                "health probe: %s not resolvable via search_path %r "
                "(POSTGRES_SCHEMA=%s)",
                ", ".join(missing),
                search_path,
                settings.postgres_schema,
            )

    database: dict[str, object] = {
        "connected": connected,
        "configured_schema": settings.postgres_schema,
        "resolved_schema": resolved_schema,
        "search_path": search_path,
        "missing_relations": missing,
    }
    if error is not None:
        database["error"] = error

    return {
        "status": "ok" if connected and not missing else "degraded",
        "database": database,
        "embedding_providers": available_providers(),
    }
