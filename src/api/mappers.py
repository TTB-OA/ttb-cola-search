"""Translate raw database rows into the shape the UI expects."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from .config import API_PREFIX
from .models import (
    ColaDetail,
    ColaSummary,
    ImageItem,
    ImageRef,
    PermitRef,
    Qualification,
)

# Materialised, indexed search surface. vw_colas is still the upstream source
# that maintains it, but the API never reads the view directly.
SEARCH_TABLE = "cola_search"
OCR_TABLE = "cola_search_ocr"

# Columns needed to build a ColaSummary. Selected explicitly so list and
# vector queries never drag along the large jsonb rollups (images,
# analyses, analysis_items, ocr_text).
SUMMARY_COLUMN_LIST: tuple[str, ...] = (
    "cola_id",
    "permit_num",
    "serial_num",
    "brand_name",
    "fanciful_name",
    "origin",
    "origin_code",
    "origin_flag",
    "class_type",
    "class_type_code",
    "ttb_ct_description",
    "ct_commodity",
    "ct_source",
    "status",
    "completed_date",
    "applicant_name",
    "primary_permit_id",
    "primary_permit_name",
    "primary_permit_city_addr",
    "primary_permit_state_addr",
    "submtr_frst_name",
    "submtr_last_name",
)

# Additional columns the detail endpoint needs on top of the summary set.
DETAIL_COLUMN_LIST: tuple[str, ...] = SUMMARY_COLUMN_LIST + (
    "status_code",
    "received_code",
    "received_description",
    "final_status_flg",
    "bottle_capacity",
    "for_sale_in",
    "vendor_code",
    "formula",
    "appellation",
    "application_type",
    "mailing_address",
    "grape_varietal",
    "grape_varietals",
    "parsed_qualifications",
    "qualifications",
    "permits",
    "submitter_id",
    "tel_no",
    "fax_no",
    "cola_details_url",
    "cola_form_url",
)


def select_columns(columns: tuple[str, ...], alias: str | None = None) -> str:
    """Render a column tuple as a SELECT list, optionally table-qualified."""
    prefix = f"{alias}." if alias else ""
    return ", ".join(f"{prefix}{c}" for c in columns)


SUMMARY_COLUMNS = select_columns(SUMMARY_COLUMN_LIST)
DETAIL_COLUMNS = select_columns(DETAIL_COLUMN_LIST)

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


def submitter_name(row: Mapping[str, Any]) -> str | None:
    name = " ".join(
        part
        for part in (row.get("submtr_frst_name"), row.get("submtr_last_name"))
        if part and part.strip()
    ).strip()
    return name or None


def permit_from_json(entry: dict[str, Any]) -> PermitRef:
    street = " ".join(
        part.strip()
        for part in (entry.get("permit_frst_strt_addr"), entry.get("permit_secnd_strt_addr"))
        if part and part.strip()
    )
    zip_code = (entry.get("permit_zip_addr") or "").strip()
    zip4 = (entry.get("permit_zip4_addr") or "").strip()
    return PermitRef(
        permit_id=entry.get("permit_id"),
        primary=bool(entry.get("primary_permit_flg")),
        name=entry.get("permit_name"),
        address=street or None,
        city=entry.get("permit_city_addr"),
        state=entry.get("permit_state_addr"),
        postal_code=(f"{zip_code}-{zip4}" if zip_code and zip4 else zip_code or None),
        country=entry.get("permit_cntry_addr"),
    )


def summary_from_row(row: Mapping[str, Any], score: float | None = None) -> ColaSummary:
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
        origin_flag=row.get("origin_flag"),
        status=row.get("status"),
        approval_date=row.get("completed_date"),
        permit=row.get("permit_num"),
        permit_id=row.get("primary_permit_id"),
        permit_name=row.get("primary_permit_name"),
        permit_city=row.get("primary_permit_city_addr"),
        permit_state=row.get("primary_permit_state_addr"),
        applicant=row.get("applicant_name") or row.get("brand_name"),
        submitter=submitter_name(row),
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


# Face ordering used for both image thumbnails and extracted-text grouping.
FACE_ORDER = {"front": 0, "back": 1, "neck": 2}


def _polygon_points(raw: Any) -> list[tuple[float, float]]:
    """Accept either a flat [x1,y1,x2,y2,...] list or a list of {x, y} points."""
    if not isinstance(raw, list) or not raw:
        return []
    if isinstance(raw[0], dict):
        pts = [
            (p.get("x"), p.get("y"))
            for p in raw
            if isinstance(p, dict) and isinstance(p.get("x"), (int, float)) and isinstance(p.get("y"), (int, float))
        ]
        return [(float(x), float(y)) for x, y in pts]
    nums = [float(v) for v in raw if isinstance(v, (int, float))]
    if len(nums) < 4:
        return []
    return list(zip(nums[0::2], nums[1::2]))


def normalized_box(
    bounding_box: Any, width_px: int | None, height_px: int | None
) -> dict[str, float] | None:
    """Return {x, y, w, h} as percentages of the image, or None when unmappable.

    Document Intelligence stores {page, unit, polygon} with absolute pixel
    coordinates, which the UI cannot position without the image dimensions.
    """
    if not isinstance(bounding_box, dict):
        return None

    # Already-normalized rectangles pass straight through.
    if all(isinstance(bounding_box.get(k), (int, float)) for k in ("x", "y", "w", "h")):
        return {k: float(bounding_box[k]) for k in ("x", "y", "w", "h")}

    points = _polygon_points(bounding_box.get("polygon"))
    if not points or not width_px or not height_px:
        return None

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)

    unit = str(bounding_box.get("unit") or "pixel").lower()
    if unit != "pixel":
        return None

    def pct(value: float, extent: int) -> float:
        return round(max(0.0, min(100.0, value / extent * 100)), 3)

    x_pct = pct(x0, width_px)
    y_pct = pct(y0, height_px)
    return {
        "x": x_pct,
        "y": y_pct,
        "w": round(min(100.0 - x_pct, pct(x1 - x0, width_px)), 3),
        "h": round(min(100.0 - y_pct, pct(y1 - y0, height_px)), 3),
    }


def image_item_from_row(row: dict[str, Any]) -> ImageItem:
    return ImageItem(
        face=image_face(row.get("img_type")) if row.get("img_type") else (row.get("file_name") or "front"),
        file=row.get("file_name"),
        type=(row.get("analysis_item_type") or "text"),
        text=row.get("text") or "",
        conf=row.get("model_confidence"),
        box=normalized_box(row.get("bounding_box"), row.get("width_px"), row.get("height_px")),
        model=row.get("analysis_model"),
    )


def _item_sort_key(item: ImageItem) -> tuple[int, str, float, float]:
    box = item.box or {}
    top = box.get("y")
    left = box.get("x")
    face = item.face or ""
    return (
        FACE_ORDER.get(face, len(FACE_ORDER)),
        face,
        float(top) if isinstance(top, (int, float)) else float("inf"),
        float(left) if isinstance(left, (int, float)) else float("inf"),
    )


def detail_from_rows(
    base: dict[str, Any],
    images: list[dict[str, Any]],
    items: list[dict[str, Any]],
) -> ColaDetail:
    summary = summary_from_row(base)
    varietals = [
        v["vartl_name"]
        for v in (base.get("grape_varietals") or [])
        if v.get("vartl_name")
    ]
    qualifications = [
        Qualification(
            id=q.get("ref_qualification_id"),
            text=q.get("qualification_text"),
            comment=q.get("qualification_comment_text"),
        )
        for q in (base.get("qualifications") or [])
    ]
    bottle_capacity = base.get("bottle_capacity")
    return ColaDetail(
        **summary.model_dump(by_alias=False),
        class_type_code=base.get("class_type_code"),
        origin_code=base.get("origin_code"),
        received_code=base.get("received_code"),
        received_description=base.get("received_description"),
        final_status=base.get("final_status_flg"),
        net_contents=str(bottle_capacity) if bottle_capacity is not None else None,
        abv=None,
        mailing_address=base.get("mailing_address"),
        application_type=base.get("application_type"),
        for_sale_in=base.get("for_sale_in"),
        vendor_code=base.get("vendor_code"),
        formula=base.get("formula"),
        appellation=base.get("appellation"),
        grape_varietals=varietals,
        qualifications=base.get("parsed_qualifications"),
        qualification_items=qualifications,
        permits=[permit_from_json(p) for p in (base.get("permits") or [])],
        submitter_id=base.get("submitter_id"),
        submitter_phone=base.get("tel_no"),
        submitter_fax=base.get("fax_no"),
        images=[image_ref_from_row(r) for r in images],
        image_items=sorted((image_item_from_row(r) for r in items), key=_item_sort_key),
        details_url=base.get("cola_details_url"),
        form_url=base.get("cola_form_url"),
    )
