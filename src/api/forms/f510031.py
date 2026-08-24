"""Redraw TTB F 5100.31 from Public COLA Registry data.

Geometry mirrors the official form (``docs/f510031.pdf``): US Legal, 612 x 1008pt,
with every numbered item drawn where the real form's widget sits. The registry
does not publish alcohol content, email address or either signature, so those
items render blank and the footer says the form was reconstructed.
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass
from datetime import UTC, datetime

from PIL import Image, ImageOps
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from ..models import ColaDetail

PAGE_W, PAGE_H = 612.0, 1008.0
LEFT, RIGHT = 18.0, 594.0
SPLIT = 250.0  # left/right column divide on the application half

BODY = "Helvetica"
BOLD = "Helvetica-Bold"

CAPTION_SIZE = 5.5
VALUE_SIZE = 8.5

# "AFFIX COMPLETE SET OF LABELS BELOW", taken from the official form's widget rect.
AFFIX_X, AFFIX_Y, AFFIX_W, AFFIX_H = 24.6, 28.9, 564.8, 297.9
AFFIX_TITLE = "AFFIX COMPLETE SET OF LABELS BELOW (See General Instructions 4 and 6)"

AFFIX_COLS = 2
AFFIX_GUTTER = 10.0
# Rows per page are chosen to land near this height, so page 1's short affix strip
# gets one tall row while a continuation page gets several.
TARGET_ROW_H = 210.0
CAPTION_H = 26.0

CONT_X, CONT_Y, CONT_W, CONT_H = LEFT, 30.0, RIGHT - LEFT, 940.0

# Label artwork is re-encoded before embedding: it bounds the PDF size and keeps
# ReportLab off image formats it can only read through PIL anyway.
MAX_IMAGE_PX = 1400
JPEG_QUALITY = 80

FOOTER_NOTE = (
    "Reconstructed from TTB Public COLA Registry data. Not an official "
    "TTB-issued certificate."
)


@dataclass(slots=True)
class LabelImage:
    """One row of ``cola_images`` plus the blob bytes, when they could be read."""

    file_name: str
    img_type: str | None = None
    face: str | None = None
    width_px: int | None = None
    height_px: int | None = None
    dimensions_txt: str | None = None
    data: bytes | None = None


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------
def _wrap(text: str, font: str, size: float, width: float) -> list[str]:
    """Greedy word wrap, breaking any single word that cannot fit on its own."""
    lines: list[str] = []
    for paragraph in str(text).splitlines():
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = ""
        for word in words:
            trial = f"{current} {word}" if current else word
            if stringWidth(trial, font, size) <= width:
                current = trial
                continue
            if current:
                lines.append(current)
            while stringWidth(word, font, size) > width and len(word) > 1:
                cut = len(word)
                while cut > 1 and stringWidth(word[:cut], font, size) > width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            current = word
        if current:
            lines.append(current)
    return lines


def _clean(value: object) -> str:
    if value is None or value is False:
        return ""
    return str(value).strip()


def _joined(*parts: object, sep: str = ", ") -> str:
    return sep.join(p for p in (_clean(v) for v in parts) if p)


# ---------------------------------------------------------------------------
# Drawing primitives
# ---------------------------------------------------------------------------
def _field(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    caption: str,
    value: str = "",
    *,
    value_size: float = VALUE_SIZE,
    value_font: str = BOLD,
) -> None:
    """A bordered form item: small caption at the top, wrapped value beneath."""
    c.setLineWidth(0.6)
    c.rect(x, y, w, h)

    inner = w - 6
    c.setFont(BODY, CAPTION_SIZE)
    cursor = y + h - CAPTION_SIZE - 2
    for line in _wrap(caption, BODY, CAPTION_SIZE, inner):
        c.drawString(x + 3, cursor, line)
        cursor -= CAPTION_SIZE + 0.8

    if not value:
        return
    cursor -= 2
    c.setFont(value_font, value_size)
    for line in _wrap(value, value_font, value_size, inner):
        if cursor < y + 2:
            break
        c.drawString(x + 4, cursor, line)
        cursor -= value_size + 1.5


def _band(c: canvas.Canvas, x: float, y: float, w: float, h: float, text: str) -> None:
    """A solid section header strip, e.g. "PART I - APPLICATION"."""
    c.setFillGray(0.85)
    c.rect(x, y, w, h, stroke=1, fill=1)
    c.setFillGray(0)
    c.setFont(BOLD, 7.5)
    c.drawString(x + 4, y + (h - 7.5) / 2 + 1.5, text)


def _checkbox(
    c: canvas.Canvas, x: float, y: float, checked: bool, label: str, size: float = 7.0
) -> None:
    c.setLineWidth(0.6)
    c.rect(x, y, 7.5, 7.5)
    if checked:
        c.setLineWidth(1.1)
        c.line(x + 1.5, y + 3.8, x + 3.2, y + 1.8)
        c.line(x + 3.2, y + 1.8, x + 6.2, y + 5.8)
        c.setLineWidth(0.6)
    c.setFont(BODY, size)
    c.drawString(x + 10.5, y + 1.3, label)


# ---------------------------------------------------------------------------
# Label artwork
# ---------------------------------------------------------------------------
def _fit_box(w: float, h: float, max_w: float, max_h: float) -> tuple[float, float]:
    """Largest w/h preserving aspect ratio that fits inside the box."""
    if w <= 0 or h <= 0 or max_w <= 0 or max_h <= 0:
        return 0.0, 0.0
    scale = min(max_w / w, max_h / h)
    return w * scale, h * scale


def _prepare_image(data: bytes) -> ImageReader | None:
    """Normalise orientation/mode and downscale, or None if it will not decode."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            im = ImageOps.exif_transpose(im) or im
            im.thumbnail((MAX_IMAGE_PX, MAX_IMAGE_PX))
            buf = io.BytesIO()
            im.convert("RGB").save(buf, format="JPEG", quality=JPEG_QUALITY)
    except Exception:  # noqa: BLE001 - a bad image must not fail the whole form
        return None
    buf.seek(0)
    return ImageReader(buf)


def _grid_rows(inner_h: float) -> int:
    return max(1, round(inner_h / TARGET_ROW_H))


def _affix_height(count: int, max_h: float) -> float:
    """How tall a continuation affix box needs to be for `count` labels.

    Page 1's box is fixed by the real form, but a spillover page holding two
    labels should not claim the whole sheet.
    """
    rows = max(1, math.ceil(count / AFFIX_COLS))
    return min(max_h, rows * TARGET_ROW_H + AFFIX_GUTTER * (rows - 1) + 21)


def _layout_images(
    images: list[LabelImage], first_capacity: int, page_capacity: int
) -> list[list[LabelImage]]:
    """Split images across the page-1 affix strip and any continuation pages."""
    if not images:
        return [[]]
    pages = [images[:first_capacity]]
    rest = images[first_capacity:]
    for start in range(0, len(rest), page_capacity):
        pages.append(rest[start : start + page_capacity])
    return pages


def _caption_lines(img: LabelImage) -> list[tuple[str, str]]:
    """(font, text) caption rows: type, then the measurements, then the file."""
    rows: list[tuple[str, str]] = []
    heading = _clean(img.img_type) or _clean(img.face).title() or "Label image"
    rows.append((BOLD, heading))

    face = _clean(img.face)
    detail: list[str] = []
    if face and face.lower() not in heading.lower():
        detail.append(face.title())
    if img.width_px and img.height_px:
        detail.append(f"{img.width_px} \u00d7 {img.height_px} px")
    if _clean(img.dimensions_txt):
        detail.append(_clean(img.dimensions_txt))
    if detail:
        rows.append((BODY, " \u00b7 ".join(detail)))

    if _clean(img.file_name):
        rows.append((BODY, _clean(img.file_name)))
    return rows


def _draw_label_cell(
    c: canvas.Canvas, img: LabelImage, x: float, y: float, w: float, h: float
) -> None:
    """One affix-grid cell: the artwork scaled to fit, with its caption below."""
    art_h = max(20.0, h - CAPTION_H)
    reader = _prepare_image(img.data) if img.data else None

    if reader is not None:
        src_w, src_h = reader.getSize()
        draw_w, draw_h = _fit_box(src_w, src_h, w, art_h)
        c.drawImage(
            reader,
            x + (w - draw_w) / 2,
            y + CAPTION_H + (art_h - draw_h) / 2,
            width=draw_w,
            height=draw_h,
            preserveAspectRatio=True,
            anchor="c",
        )
    else:
        c.setLineWidth(0.5)
        c.setDash(2, 2)
        c.rect(x, y + CAPTION_H, w, art_h)
        c.setDash()
        c.setFont(BODY, 7)
        c.setFillGray(0.45)
        c.drawCentredString(x + w / 2, y + CAPTION_H + art_h / 2, "image unavailable")
        c.setFillGray(0)

    cursor = y + CAPTION_H - 8
    for font, text in _caption_lines(img):
        if cursor < y:
            break
        c.setFont(font, 6.5)
        line = _wrap(text, font, 6.5, w)[:1]
        if line:
            c.drawCentredString(x + w / 2, cursor, line[0])
        cursor -= 8


def _draw_affix_grid(
    c: canvas.Canvas,
    page_images: list[LabelImage],
    x: float,
    y: float,
    w: float,
    h: float,
    rows: int,
) -> None:
    cell_w = (w - AFFIX_GUTTER * (AFFIX_COLS - 1)) / AFFIX_COLS
    cell_h = (h - AFFIX_GUTTER * (rows - 1)) / rows
    for i, img in enumerate(page_images):
        col, row = i % AFFIX_COLS, i // AFFIX_COLS
        _draw_label_cell(
            c,
            img,
            x + col * (cell_w + AFFIX_GUTTER),
            y + h - (row + 1) * cell_h - row * AFFIX_GUTTER,
            cell_w,
            cell_h,
        )


# ---------------------------------------------------------------------------
# Value derivation
# ---------------------------------------------------------------------------
def _applicant_block(detail: ColaDetail) -> str:
    primary = next((p for p in detail.permits if p.primary), None)
    if primary is None and detail.permits:
        primary = detail.permits[0]
    if primary is None:
        return _joined(detail.applicant, detail.permit_city, detail.permit_state)
    locality = _joined(
        primary.city, _joined(primary.state, primary.postal_code, sep=" ")
    )
    return "\n".join(
        part
        for part in (
            _clean(primary.name) or _clean(detail.applicant),
            _clean(primary.address),
            locality,
            _clean(primary.country),
        )
        if part
    )


def _qualifications(detail: ColaDetail) -> str:
    if detail.qualification_items:
        return "\n".join(
            _joined(q.text, q.comment, sep=" — ") for q in detail.qualification_items
        )
    return _clean(detail.qualifications)


def _application_flags(detail: ColaDetail) -> dict[str, bool]:
    """Which of items 14a-d the scraped "TYPE OF APPLICATION" string selected."""
    text = _clean(detail.application_type).lower()
    return {
        "a": "label approval" in text and "exemption" not in text,
        "b": "exemption" in text,
        "c": "distinctive" in text,
        "d": "resubmission" in text,
    }


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
def _draw_footer(c: canvas.Canvas, detail: ColaDetail, page: int, total: int) -> None:
    c.setFont(BODY, 6)
    c.setFillGray(0.35)
    c.drawString(LEFT, 14, "TTB F 5100.31 (04/2023) \u2014 " + FOOTER_NOTE)
    c.drawRightString(
        RIGHT, 14, f"TTB ID {_clean(detail.ttb_id)}  \u00b7  Page {page} of {total}"
    )
    c.setFillGray(0)


def _draw_application(c: canvas.Canvas, detail: ColaDetail) -> None:
    """Page 1: the form itself, everything above the affix strip."""
    c.setFont(BODY, 6.5)
    c.drawRightString(RIGHT, 996, "OMB No. 1513-0020")

    _field(
        c,
        LEFT,
        930,
        SPLIT - LEFT,
        62,
        "FOR TTB USE ONLY",
        "\n".join(
            filter(
                None,
                (
                    f"TTB ID   {_clean(detail.ttb_id)}",
                    _joined("STATUS", detail.status, sep="   "),
                    _joined("CLASS/TYPE", detail.class_type or detail.class_sub, sep="   "),
                    _joined("ORIGIN", detail.origin, sep="   "),
                ),
            )
        ),
        value_size=6.5,
        value_font=BODY,
    )

    c.setLineWidth(0.6)
    c.rect(SPLIT, 930, RIGHT - SPLIT, 62)
    mid = SPLIT + (RIGHT - SPLIT) / 2
    for offset, font, size, text in (
        (12, BODY, 7.5, "DEPARTMENT OF THE TREASURY"),
        (22, BODY, 7.5, "ALCOHOL AND TOBACCO TAX AND TRADE BUREAU"),
        (34, BOLD, 8.5, "APPLICATION FOR AND CERTIFICATION/EXEMPTION OF"),
        (44, BOLD, 8.5, "LABEL/BOTTLE APPROVAL"),
        (53, BODY, 6, "(See Instructions and Paperwork Reduction Act Notice Below)"),
    ):
        c.setFont(font, size)
        c.drawCentredString(mid, 930 + 62 - offset, text)

    _band(c, LEFT, 916, RIGHT - LEFT, 13, "PART I - APPLICATION")

    left_w = SPLIT - LEFT
    _field(c, LEFT, 892, left_w, 24, "1. REP. ID. NO. (If any)", _clean(detail.vendor_code))
    _field(
        c,
        LEFT,
        866,
        left_w,
        26,
        "2. PLANT REGISTRY/BASIC PERMIT/BREWER'S NO. (Required)",
        _clean(detail.permit_id) or _clean(detail.permit),
    )

    _field(c, LEFT, 836, left_w, 30, "3. SOURCE OF PRODUCT (Required)")
    source = _clean(detail.origin_group).lower()
    _checkbox(c, LEFT + 12, 840, source == "domestic", "DOMESTIC")
    _checkbox(c, LEFT + 92, 840, source == "imported", "IMPORTED")

    _field(c, LEFT, 796, 124, 40, "4. SERIAL NUMBER (Required)", _clean(detail.serial))
    _field(c, LEFT + 124, 796, left_w - 124, 40, "5. TYPE OF PRODUCT (Required)")
    category = _clean(detail.category).lower()
    for i, (label, match) in enumerate(
        (("WINE", "wine"), ("DISTILLED SPIRITS", "distilled"), ("MALT BEVERAGES", "malt"))
    ):
        _checkbox(c, LEFT + 130, 819 - i * 9.5, match in category, label, size=6)

    _field(c, LEFT, 770, left_w, 26, "6. BRAND NAME (Required)", _clean(detail.brand))
    _field(c, LEFT, 744, left_w, 26, "7. FANCIFUL NAME (If any)", _clean(detail.fanciful))

    right_w = RIGHT - SPLIT
    _field(
        c,
        SPLIT,
        830,
        right_w,
        86,
        "8. NAME AND ADDRESS OF APPLICANT AS SHOWN ON PLANT REGISTRY, BASIC PERMIT, "
        "OR BREWER'S NOTICE. INCLUDE APPROVED DBA OR TRADENAME IF USED ON THE LABEL "
        "(Required)",
        _applicant_block(detail),
        value_size=8,
    )
    _field(
        c,
        SPLIT,
        744,
        right_w,
        86,
        "8a. MAILING ADDRESS, IF DIFFERENT",
        _clean(detail.mailing_address),
        value_size=8,
    )

    _field(c, LEFT, 716, 124, 28, "9. FORMULA", _clean(detail.formula))
    _field(
        c,
        LEFT + 124,
        716,
        232,
        28,
        "10. GRAPE VARIETAL(S) Wine only",
        ", ".join(detail.grape_varietals),
        value_size=7.5,
    )
    _field(
        c,
        LEFT,
        684,
        356,
        32,
        "11. WINE APPELLATION (If on label)",
        _clean(detail.appellation),
    )
    _field(c, LEFT, 650, 124, 34, "12. PHONE NUMBER", _clean(detail.submitter_phone))
    _field(c, LEFT + 124, 650, 232, 34, "13. EMAIL ADDRESS")

    flags = _application_flags(detail)
    _field(c, 378, 650, RIGHT - 378, 94, "14. TYPE OF APPLICATION (Check applicable box(es))")
    _checkbox(c, 384, 726, flags["a"], "a. CERTIFICATE OF LABEL APPROVAL", size=6)
    _checkbox(c, 384, 712, flags["b"], "b. CERTIFICATE OF EXEMPTION FROM LABEL", size=6)
    c.setFont(BODY, 6)
    c.drawString(394.5, 703, 'APPROVAL "For sale in ____ only"')
    _checkbox(c, 384, 688, flags["c"], "c. DISTINCTIVE LIQUOR BOTTLE APPROVAL.", size=6)
    c.setFont(BODY, 6)
    c.drawString(394.5, 679, "TOTAL BOTTLE CAPACITY BEFORE CLOSURE")
    c.setFont(BOLD, 7)
    c.drawString(394.5, 670, _clean(detail.net_contents))
    _checkbox(c, 384, 656, flags["d"], "d. RESUBMISSION AFTER REJECTION", size=6)

    _field(
        c,
        LEFT,
        580,
        RIGHT - LEFT,
        60,
        "15. SHOW ANY INFORMATION THAT IS BLOWN, BRANDED, OR EMBOSSED ON THE CONTAINER "
        "(e.g., net contents) ONLY IF IT DOES NOT APPEAR ON THE LABELS AFFIXED BELOW. "
        "ALSO, SHOW TRANSLATIONS OF FOREIGN LANGUAGE TEXT APPEARING ON LABELS.",
    )

    _band(c, LEFT, 562, RIGHT - LEFT, 13, "PART II - APPLICANT'S CERTIFICATION")
    c.setFont(BODY, 6)
    cursor = 552
    certification = (
        "Under the penalties of perjury, I declare: that all statements appearing on this "
        "application are true and correct to the best of my knowledge and belief; and, that "
        "the representations on the labels attached to this form, including supplemental "
        "documents, truly and correctly represent the content of the containers to which "
        "these labels will be applied. I also certify that I have read, understood, and "
        "complied with the conditions and instructions which are attached to an original "
        "TTB F 5100.31, Certificate/Exemption of Label/Bottle Approval."
    )
    for line in _wrap(certification, BODY, 6, RIGHT - LEFT - 4):
        c.drawString(LEFT + 2, cursor, line)
        cursor -= 7.5

    _field(c, LEFT, 486, 110, 26, "16. DATE OF APPLICATION")
    _field(c, LEFT + 110, 486, 234, 26, "17. SIGNATURE OF APPLICANT OR AUTHORIZED AGENT")
    _field(
        c,
        LEFT + 344,
        486,
        RIGHT - LEFT - 344,
        26,
        "18. PRINT NAME OF APPLICANT OR AUTHORIZED AGENT",
        _clean(detail.submitter),
    )

    _band(c, LEFT, 466, RIGHT - LEFT, 13, "PART III - TTB CERTIFICATE")
    c.setFont(BODY, 6)
    c.drawString(
        LEFT + 2,
        457,
        "This certificate is issued subject to applicable laws, regulations, and conditions "
        "as set forth in the instructions portion of this form.",
    )

    _field(
        c,
        LEFT,
        428,
        124,
        26,
        "19. DATE ISSUED",
        detail.approval_date.strftime("%m/%d/%Y") if detail.approval_date else "",
    )
    _field(
        c,
        LEFT + 124,
        428,
        RIGHT - LEFT - 124,
        26,
        "20. AUTHORIZED SIGNATURE, ALCOHOL AND TOBACCO TAX AND TRADE BUREAU",
    )

    _band(c, LEFT, 412, RIGHT - LEFT, 13, "FOR TTB USE ONLY")
    _field(c, LEFT, 336, 458, 74, "QUALIFICATIONS", _qualifications(detail), value_size=7)
    _field(c, LEFT + 458, 336, RIGHT - LEFT - 458, 74, "EXPIRATION DATE (If any)")


def _draw_affix_page(
    c: canvas.Canvas,
    page_images: list[LabelImage],
    x: float,
    y: float,
    w: float,
    h: float,
    title: str,
) -> None:
    c.setLineWidth(0.8)
    c.rect(x, y, w, h)
    c.setFont(BOLD, 7)
    c.drawString(x + 4, y + h - 9, title)

    inner_y, inner_h = y + 4, h - 17
    if not page_images:
        c.setFont(BODY, 7.5)
        c.setFillGray(0.45)
        c.drawCentredString(
            x + w / 2,
            inner_y + inner_h / 2,
            "No label artwork has been retrieved for this record.",
        )
        c.setFillGray(0)
        return
    _draw_affix_grid(
        c,
        page_images,
        x + 4,
        inner_y,
        w - 8,
        inner_h,
        # Only as many rows as are occupied, so a part-full page grows its cells
        # instead of reserving space for labels that are not there.
        min(_grid_rows(inner_h), math.ceil(len(page_images) / AFFIX_COLS)),
    )


def render_f510031(detail: ColaDetail, images: list[LabelImage]) -> bytes:
    """Render the form for ``detail``, flowing ``images`` through the affix area."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))
    c.setTitle(f"TTB F 5100.31 - {_clean(detail.ttb_id)}")
    c.setAuthor("TTB Public COLA Registry")
    c.setSubject(
        "Generated "
        + datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
        + " from the TTB Public COLA Registry"
    )

    first_capacity = _grid_rows(AFFIX_H - 17) * AFFIX_COLS
    page_capacity = _grid_rows(CONT_H - 17) * AFFIX_COLS
    pages = _layout_images(images, first_capacity, page_capacity)
    total = len(pages)

    _draw_application(c, detail)
    _draw_affix_page(c, pages[0], AFFIX_X, AFFIX_Y, AFFIX_W, AFFIX_H, AFFIX_TITLE)
    _draw_footer(c, detail, 1, total)

    for number, page_images in enumerate(pages[1:], start=2):
        c.showPage()
        height = _affix_height(len(page_images), CONT_H)
        _draw_affix_page(
            c,
            page_images,
            CONT_X,
            # Top-aligned, so the shrunken box hangs from the same edge as page 1.
            CONT_Y + CONT_H - height,
            CONT_W,
            height,
            f"{AFFIX_TITLE} \u2014 continued",
        )
        _draw_footer(c, detail, number, total)

    c.showPage()
    c.save()
    return buf.getvalue()
