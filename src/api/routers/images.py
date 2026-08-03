"""Label image proxy — streams private blob bytes through the API."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ..blob import stream_blob
from ..db import fetch_one

router = APIRouter(tags=["images"])


@router.get("/colas/{cola_id}/images/{file_name}")
async def get_image(cola_id: int, file_name: str):
    if file_name == "primary":
        row = await fetch_one(
            "SELECT file_name, blob_name, blob_url FROM cola_images WHERE cola_id = %s "
            "ORDER BY CASE upper(coalesce(img_type,'')) WHEN 'FRONT' THEN 0 ELSE 1 END, "
            "file_name LIMIT 1",
            [cola_id],
        )
    else:
        row = await fetch_one(
            "SELECT file_name, blob_name, blob_url FROM cola_images "
            "WHERE cola_id = %s AND file_name = %s",
            [cola_id, file_name],
        )

    if row is None:
        raise HTTPException(status_code=404, detail="Image not found")

    blob_name = row.get("blob_name")
    if not blob_name:
        raise HTTPException(status_code=404, detail="Image blob not available")

    try:
        chunks, content_type = await stream_blob(blob_name)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Image backend unavailable") from exc

    return StreamingResponse(
        chunks,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )
