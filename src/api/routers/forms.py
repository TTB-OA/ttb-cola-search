"""Render TTB F 5100.31 as a PDF for a single COLA."""
from __future__ import annotations

import asyncio
import math

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from ..blob import read_blob
from ..config import get_settings
from ..db import fetch_all
from ..forms.f510031 import LabelImage, render_f510031
from ..mappers import image_display_order_sql, image_face, visual_interest_join_sql
from ..ratelimit import SlidingWindowLimiter, client_key
from .colas import load_detail

router = APIRouter(tags=["colas"])

# A COLA can carry dozens of images; past this the form is unusable as a form and
# the render cost stops being worth it.
MAX_FORM_IMAGES = 16

_limiter: SlidingWindowLimiter | None = None


def _form_limiter() -> SlidingWindowLimiter:
    global _limiter
    if _limiter is None:
        settings = get_settings()
        _limiter = SlidingWindowLimiter(
            settings.form_render_rate_limit,
            settings.form_render_rate_window_seconds,
        )
    return _limiter


async def _label_images(cola_id: str) -> list[LabelImage]:
    """The COLA's artwork in gallery order, with blob bytes where readable."""
    rows = await fetch_all(
        "SELECT ci.file_name, ci.img_type, ci.width_px, ci.height_px, "
        "ci.dimensions_txt, ci.blob_name "
        "FROM cola_images ci "
        f"{visual_interest_join_sql('ci')} "
        "WHERE ci.cola_id = %s AND ci.blob_name IS NOT NULL "
        f"ORDER BY {image_display_order_sql('ci')} LIMIT %s",
        [cola_id, MAX_FORM_IMAGES],
    )

    blobs = await asyncio.gather(
        *(read_blob(r["blob_name"]) for r in rows), return_exceptions=True
    )
    return [
        LabelImage(
            file_name=row["file_name"],
            img_type=row["img_type"],
            face=image_face(row["img_type"]),
            width_px=row["width_px"],
            height_px=row["height_px"],
            dimensions_txt=row["dimensions_txt"],
            # A blob that will not read leaves a captioned placeholder rather
            # than failing the whole form.
            data=blob if isinstance(blob, bytes) else None,
        )
        for row, blob in zip(rows, blobs, strict=True)
    ]


@router.get(
    "/colas/{cola_id}/form.pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
    summary="TTB F 5100.31 for a COLA",
    description=(
        "Renders TTB Form 5100.31 (Application for and Certification/Exemption of "
        "Label/Bottle Approval) for one COLA from the registry data, with the label "
        "artwork placed in the form's affix area. Items the registry does not publish "
        "(alcohol content, email address, both signatures) are left blank. This is a "
        "reconstruction, not the certificate TTB issued."
    ),
)
async def get_cola_form(cola_id: str, request: Request) -> Response:
    settings = get_settings()
    retry_after = _form_limiter().check(
        client_key(request, settings.trust_forwarded_for)
    )
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="Too many form renders. Try again shortly.",
            headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
        )

    detail = await load_detail(cola_id)
    images = await _label_images(cola_id)
    # ReportLab and Pillow are synchronous and CPU-bound; keep them off the loop.
    pdf = await asyncio.to_thread(render_f510031, detail, images)

    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'inline; filename="TTB-F-5100-31-{detail.ttb_id}.pdf"'
            ),
            "Cache-Control": "private, max-age=300",
        },
    )
