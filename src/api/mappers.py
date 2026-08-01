"""Translate raw database rows into the shape the UI expects."""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from .config import API_PREFIX
from .models import ColaDetail, ColaSummary, ImageItem, ImageRef

# vw_colas.ct_commodity code -> UI commodity label
COMMODITY_LABEL = {
    "wine": "Wine",
    "beer": "Malt Beverage",
    "distilled_spirits": "Distilled Spirits",
    "unknown": "Other",
}
# UI commodity label -> ct_commodity code (for filtering)
COMMODITY_CODE = {v: k for k, v in COMMODITY_LABEL.items()}

# vw_colas.ct_source code -> UI source label
SOURCE_LABEL = {"domestic": "Domestic", "import": "Imported", "unknown": "Imported"}
SOURCE_CODE = {"Domestic": "domestic", "Imported": "import"}


def commodity_label(code: str | None) -> str:
    return COMMODITY_LABEL.get((code or "").lower(), "Other")


def source_label(code: str | None) -> str:
    return SOURCE_LABEL.get((code or "").lower(), "Imported")


def image_face(img_type: str | None) -> str:
    return (img_type or "other").strip().lower()


def image_url(cola_id: int, file_name: str) -> str:
    return f"{API_PREFIX}/colas/{cola_id}/images/{quote(file_name)}"


def thumb_url(cola_id: int) -> str:
    return f"{API_PREFIX}/colas/{cola_id}/images/primary"


def summary_from_row(row: dict[str, Any], score: float | None = None) -> ColaSummary:
    cola_id = row["cola_id"]
    return ColaSummary(
        id=cola_id,
        ttb_id=str(cola_id),
        serial=row.get("serial_num"),
        brand=row.get("brand_name"),
        fanciful=row.get("fanciful_name"),
        category=commodity_label(row.get("ct_commodity")),
        class_type=row.get("class_type"),
        class_sub=row.get("ttb_ct_description"),
        origin=row.get("origin"),
        origin_group=source_label(row.get("ct_source")),
        status=row.get("status"),
        approval_date=row.get("completed_date"),
        permit=row.get("permit_num"),
        applicant=row.get("applicant_name") or row.get("brand_name"),
        thumb_url=thumb_url(cola_id),
        score=score,
    )


def image_ref_from_row(row: dict[str, Any]) -> ImageRef:
    cola_id = row["cola_id"]
    file_name = row["file_name"]
    return ImageRef(
        file_name=file_name,
        face=image_face(row.get("img_type")),
        img_type=row.get("img_type"),
        url=image_url(cola_id, file_name),
        width_px=row.get("width_px"),
        height_px=row.get("height_px"),
    )


def image_item_from_row(row: dict[str, Any]) -> ImageItem:
    return ImageItem(
        face=image_face(row.get("img_type")) if row.get("img_type") else (row.get("file_name") or "front"),
        file=row.get("file_name"),
        type=(row.get("analysis_item_type") or "text"),
        text=row.get("text") or "",
        conf=row.get("model_confidence"),
        box=row.get("bounding_box"),
        model=row.get("analysis_model"),
    )


def detail_from_rows(
    base: dict[str, Any],
    images: list[dict[str, Any]],
    items: list[dict[str, Any]],
    varietals: list[str],
    qualifications: str | None,
) -> ColaDetail:
    summary = summary_from_row(base)
    return ColaDetail(
        **summary.model_dump(by_alias=False),
        class_type_code=base.get("class_type_code"),
        origin_code=base.get("origin_code"),
        received_date=None,
        net_contents=base.get("bottle_capacity"),
        abv=None,
        mailing_address=base.get("mailing_address"),
        application_type=base.get("application_type"),
        for_sale_in=base.get("for_sale_in"),
        vendor_code=base.get("vendor_code"),
        formula=base.get("formula"),
        appellation=base.get("appellation"),
        grape_varietals=varietals,
        qualifications=qualifications or base.get("parsed_qualifications"),
        images=[image_ref_from_row(r) for r in images],
        image_items=[image_item_from_row(r) for r in items],
        details_url=base.get("cola_details_url"),
        form_url=base.get("cola_form_url"),
    )
