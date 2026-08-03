"""Health and readiness endpoints."""
from __future__ import annotations

from fastapi import APIRouter

from ..db import fetch_one
from ..embedding import available_providers

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, object]:
    database_ok = True
    try:
        await fetch_one("SELECT 1 AS ok")
    except Exception:  # noqa: BLE001 - health endpoint should degrade, not fail hard
        database_ok = False
    return {
        "status": "ok" if database_ok else "degraded",
        "database": database_ok,
        "embedding_providers": available_providers(),
    }
