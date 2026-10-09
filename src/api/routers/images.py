"""Label image proxy — streams private blob bytes through the API."""
from __future__ import annotations

import asyncio
import io

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from PIL import Image

from ..blob import stream_blob
from ..db import fetch_one
from ..mappers import image_display_order_sql, visual_interest_hero_join_sql

router = APIRouter(tags=["images"])

CACHE_HEADERS = {"Cache-Control": "public, max-age=86400"}
JPEG_QUALITY = 90


def tiff_to_jpeg(data: bytes) -> bytes | None:
    """Re-encode a TIFF as JPEG (only Safari renders TIFF), or None if it won't decode."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info:
                rgba = im.convert("RGBA")
                im = Image.new("RGB", rgba.size, "white")
                im.paste(rgba, mask=rgba.getchannel("A"))
            buf = io.BytesIO()
            im.convert("RGB").save(buf, format="JPEG", quality=JPEG_QUALITY)
    except Exception:  # noqa: BLE001 - fall back to the original bytes
        return None
    return buf.getvalue()


@router.get("/colas/{cola_id}/images/{file_name}")
async def get_image(cola_id: str, file_name: str):
    if file_name == "primary":
        # Scores are not joined here: the hero column alone decides the winner, and
        # skipping the `images` rollup keeps this hot endpoint off the toast table.
        row = await fetch_one(
            "SELECT ci.file_name, ci.blob_name, ci.blob_url FROM cola_images ci "
            f"{visual_interest_hero_join_sql('ci')} "
            "WHERE ci.cola_id = %s "
            f"ORDER BY {image_display_order_sql('ci', out=None)} LIMIT 1",
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
        if content_type == "image/tiff":
            data = b"".join([chunk async for chunk in chunks])
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Image backend unavailable") from exc

    if content_type == "image/tiff":
        jpeg = await asyncio.to_thread(tiff_to_jpeg, data)
        if jpeg is not None:
            return Response(jpeg, media_type="image/jpeg", headers=CACHE_HEADERS)
        return Response(data, media_type=content_type, headers=CACHE_HEADERS)

    return StreamingResponse(chunks, media_type=content_type, headers=CACHE_HEADERS)
