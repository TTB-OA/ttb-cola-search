"""Redraw TTB F 5100.31 from Public COLA Registry data.

Geometry mirrors the official form (``docs/f510031.pdf``): US Legal, 612 x 1008pt,
with every numbered item drawn where the real form's widget sits. The registry
does not publish alcohol content, email address, the item 15 container text or
either signature, so those items render blank and the footer says the form was
reconstructed.
"""
from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime

from PIL import Image, ImageOps
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from ..models import ColaDetail, PermitRef

PAGE_W, PAGE_H = 612.0, 1008.0
LEFT, RIGHT = 18.0, 594.0
SPLIT = 250.0  # left/right column divide on the application half

BODY = "Helvetica"
BOLD = "Helvetica-Bold"

# Registry data is drawn in blue monospace so it reads as fill-in rather than
# as part of the preprinted form.
MONO = "Courier"
MONO_BOLD = "Courier-Bold"
VALUE_COLOR = (0.05, 0.20, 0.62)

CAPTION_SIZE = 5.5
VALUE_SIZE = 9.0

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

# Page 1's "QUALIFICATIONS" box is fixed by the real form; anything that will not
# fit inside it is moved wholesale to an addendum page, as is the permit list
# whenever a record carries more than one permit.
QUAL_BOX_W, QUAL_BOX_H, QUAL_BOX_SIZE = 458.0, 74.0, 7.5
ADDENDUM_SIZE = 8.0
ADDENDUM_LEAD = ADDENDUM_SIZE + 3.5
QUAL_TITLE = "QUALIFICATIONS (CONTINUED FROM PART III)"
PERMIT_TITLE = "ASSOCIATED PERMITS (CONTINUED FROM ITEM 2)"

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


def _coded(code: object, value: object) -> str:
    """A registry code with its description, either half of which may be absent."""
    code_text = _clean(code)
    value_text = _clean(value)
    if code_text and value_text:
        return f"{code_text} - {value_text}"
    return code_text or value_text


def _phone(value: object) -> str:
    """Format a North American number; anything else is passed through as-is."""
    text = _clean(value)
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[0:3]}) {digits[3:6]}-{digits[6:]}"
    if len(digits) == 7:
        return f"{digits[0:3]}-{digits[3:]}"
    return text


def _date(value: date | None) -> str:
    return value.strftime("%m/%d/%Y") if value else ""


def _value_style(c: canvas.Canvas, font: str, size: float) -> None:
    c.setFont(font, size)
    c.setFillColorRGB(*VALUE_COLOR)


def _reset_style(c: canvas.Canvas) -> None:
    c.setFillGray(0)


# ---------------------------------------------------------------------------
# Drawing primitives
# ---------------------------------------------------------------------------
def _draw_box_caption(
    c: canvas.Canvas, x: float, y: float, w: float, h: float, caption: str
) -> float:
    """Border plus wrapped caption for a form item; returns the y to draw values at."""
    c.setLineWidth(0.6)
    c.rect(x, y, w, h)
    inner = w - 6
    c.setFont(BODY, CAPTION_SIZE)
    cursor = y + h - CAPTION_SIZE - 2
    for line in _wrap(caption, BODY, CAPTION_SIZE, inner):
        c.drawString(x + 3, cursor, line)
        cursor -= CAPTION_SIZE + 0.8
    return cursor - 2


def _value_area_height(h: float, caption: str, inner: float) -> float:
    """Usable value height for a `_draw_box_caption` box of height `h`."""
    lines = len(_wrap(caption, BODY, CAPTION_SIZE, inner))
    return h - CAPTION_SIZE - 6 - lines * (CAPTION_SIZE + 0.8)


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
    value_font: str = MONO_BOLD,
    autosize: bool = False,
    min_value_size: float = 5.0,
) -> None:
    """A bordered form item: small caption at the top, wrapped value beneath.

    With `autosize`, the value font shrinks (down to `min_value_size`) so long
    content wraps to fit the box's remaining space instead of being cut off.
    """
    cursor = _draw_box_caption(c, x, y, w, h, caption)
    if not value:
        return
    inner = w - 6
    size = value_size
    lines = _wrap(value, value_font, size, inner)
    if autosize:
        avail_h = cursor - (y + 2)
        while size > min_value_size and len(lines) * (size + 1.5) > avail_h:
            size -= 0.5
            lines = _wrap(value, value_font, size, inner)
    _value_style(c, value_font, size)
    for line in lines:
        if cursor < y + 2:
            break
        c.drawString(x + 4, cursor, line)
        cursor -= size + 1.5
    _reset_style(c)


def _draw_paragraphs(
    c: canvas.Canvas,
    x: float,
    cursor: float,
    width: float,
    items: list[str],
    *,
    font: str = MONO_BOLD,
    size: float = VALUE_SIZE,
    gap: float = 3.0,
) -> None:
    """Draw pre-fitted paragraphs, each on its own wrapped lines, top to bottom."""
    _value_style(c, font, size)
    for idx, item in enumerate(items):
        if idx:
            cursor -= gap
        for line in _wrap(item, font, size, width):
            c.drawString(x, cursor, line)
            cursor -= size + 1.5
    _reset_style(c)


def _field_value_lines(h: float, w: float, caption: str, value_size: float) -> int:
    """How many value lines `_field` can draw before it runs out of box."""
    cursor = h - CAPTION_SIZE - 2
    for _ in _wrap(caption, BODY, CAPTION_SIZE, w - 6):
        cursor -= CAPTION_SIZE + 0.8
    cursor -= 2
    count = 0
    while cursor >= 2:
        count += 1
        cursor -= value_size + 1.5
    return count


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
        c.setStrokeColorRGB(*VALUE_COLOR)
        c.line(x + 1.5, y + 3.8, x + 3.2, y + 1.8)
        c.line(x + 3.2, y + 1.8, x + 6.2, y + 5.8)
        c.setStrokeGray(0)
        c.setLineWidth(0.6)
    c.setFont(BODY, size)
    c.drawString(x + 10.5, y + 1.3, label)


def _inline_value(
    c: canvas.Canvas,
    x: float,
    y: float,
    label: str,
    value: str,
    *,
    size: float = 6.0,
    placeholder: str = "",
) -> float:
    """Draw preprinted `label` then its registry `value`; returns the trailing x."""
    c.setFont(BODY, size)
    c.drawString(x, y, label)
    x += stringWidth(label, BODY, size)
    if value:
        _value_style(c, MONO_BOLD, size + 0.5)
        c.drawString(x, y, value)
        _reset_style(c)
        return x + stringWidth(value, MONO_BOLD, size + 0.5)
    c.setFont(BODY, size)
    c.drawString(x, y, placeholder)
    return x + stringWidth(placeholder, BODY, size)


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
    rows.append((MONO_BOLD, heading))

    face = _clean(img.face)
    detail: list[str] = []
    if face and face.lower() not in heading.lower():
        detail.append(face.title())
    if img.width_px and img.height_px:
        detail.append(f"{img.width_px} \u00d7 {img.height_px} px")
    if _clean(img.dimensions_txt):
        detail.append(_clean(img.dimensions_txt))
    if detail:
        rows.append((MONO, " \u00b7 ".join(detail)))

    if _clean(img.file_name):
        rows.append((MONO, _clean(img.file_name)))
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
        _value_style(c, font, 7.0)
        line = _wrap(text, font, 7.0, w)[:1]
        if line:
            c.drawCentredString(x + w / 2, cursor, line[0])
        cursor -= 8
    _reset_style(c)


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
def _permit_numbers(detail: ColaDetail) -> str:
    """All distinct permit numbers, primary permit(s) first, for item 2."""
    ordered = sorted(detail.permits, key=lambda p: not p.primary)
    seen: list[str] = []
    for permit in ordered:
        permit_id = _clean(permit.permit_id)
        if permit_id and permit_id not in seen:
            seen.append(permit_id)
    if not seen:
        fallback = _clean(detail.permit_id) or _clean(detail.permit)
        if fallback:
            seen.append(fallback)
    return ", ".join(seen)


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


def _address_key(value: str) -> str:
    """Letters and digits only, so punctuation and spacing do not defeat a match."""
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _mailing_address(detail: ColaDetail, applicant_block: str) -> str:
    """Item 8a, blank when it only repeats the address already in item 8."""
    mailing = _clean(detail.mailing_address)
    key = _address_key(mailing)
    block = _address_key(applicant_block)
    if key and block and (key in block or block in key):
        return ""
    return mailing


def _qualification_texts(detail: ColaDetail) -> list[str]:
    """One string per qualification, from the parsed items or the raw blob."""
    if detail.qualification_items:
        texts = (
            _joined(q.text, q.comment, sep=" \u2014 ") for q in detail.qualification_items
        )
    else:
        texts = (line for line in _clean(detail.qualifications).splitlines())
    return [t for t in (t.strip() for t in texts) if t]


def _qualifications(detail: ColaDetail) -> str:
    return "\n".join(_qualification_texts(detail))


def _qualification_rows(texts: list[str], width: float) -> list[tuple[str, str]]:
    """(marker, text) rows for the addendum; the marker is blank on wrapped lines."""
    marker_w = stringWidth("00. ", MONO_BOLD, ADDENDUM_SIZE)
    rows: list[tuple[str, str]] = []
    for i, text in enumerate(texts, start=1):
        for j, line in enumerate(_wrap(text, MONO_BOLD, ADDENDUM_SIZE, width - marker_w)):
            rows.append((f"{i}." if j == 0 else "", line))
        rows.append(("", ""))
    return rows[:-1] if rows else rows


def _permit_rows(permits: list[PermitRef], width: float) -> list[tuple[str, str]]:
    """(marker, text) rows listing every permit with its name and premises."""
    marker_w = stringWidth("00. ", MONO_BOLD, ADDENDUM_SIZE)
    rows: list[tuple[str, str]] = []
    for i, permit in enumerate(permits, start=1):
        head = _clean(permit.permit_id) or "\u2014"
        if permit.primary:
            head += "   (PRIMARY)"
        rows.append((f"{i}.", head))
        parts = (
            _clean(permit.name),
            _clean(permit.address),
            _joined(permit.city, _joined(permit.state, permit.postal_code, sep=" ")),
            _clean(permit.country),
        )
        for part in (p for p in parts if p):
            for line in _wrap(part, MONO_BOLD, ADDENDUM_SIZE, width - marker_w):
                rows.append(("", line))
        rows.append(("", ""))
    return rows[:-1] if rows else rows


def _paginate_rows(rows: list[tuple[str, str]], h: float) -> list[list[tuple[str, str]]]:
    per_page = max(1, int((h - 21) // ADDENDUM_LEAD))
    return [rows[i : i + per_page] for i in range(0, len(rows), per_page)]


def _addendum_ref(kind: str, start: int, count: int) -> str:
    where = f"page {start}" if count == 1 else f"pages {start}-{start + count - 1}"
    return f"See {kind} addendum, {where}."


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


def _draw_application(
    c: canvas.Canvas,
    detail: ColaDetail,
    permit_value: str = "",
    qualifications: str = "",
) -> None:
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
                    f"TTB ID:   {_clean(detail.ttb_id)}",
                    _joined("STATUS:", detail.status, sep="   "),
                    _joined(
                        "CLASS/TYPE:",
                        _coded(detail.class_type_code, detail.class_type or detail.class_sub),
                        sep="   ",
                    ),
                    _joined("ORIGIN:", _coded(detail.origin_code, detail.origin), sep="   "),
                ),
            )
        ),
        value_size=7.0,
        value_font=MONO,
        autosize=True,
        min_value_size=5.5,
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
        permit_value,
    )

    _field(c, LEFT, 836, left_w, 30, "3. SOURCE OF PRODUCT (Required)")
    # The scraped form item is authoritative; origin_group is the API's inference.
    source = (_clean(detail.source_of_product) or _clean(detail.origin_group)).lower()
    _checkbox(c, LEFT + 12, 840, source == "domestic", "DOMESTIC")
    _checkbox(c, LEFT + 92, 840, source == "imported", "IMPORTED")

    _field(c, LEFT, 796, 124, 40, "4. SERIAL NUMBER (Required)", _clean(detail.serial))
    _field(c, LEFT + 124, 796, left_w - 124, 40, "5. TYPE OF PRODUCT (Required)")
    product = (_clean(detail.type_of_product) or _clean(detail.category)).lower()
    for i, (label, match) in enumerate(
        (("WINE", "wine"), ("DISTILLED SPIRITS", "distilled"), ("MALT BEVERAGES", "malt"))
    ):
        _checkbox(c, LEFT + 130, 819 - i * 9.5, match in product, label, size=6)

    _field(c, LEFT, 770, left_w, 26, "6. BRAND NAME (Required)", _clean(detail.brand))
    _field(c, LEFT, 744, left_w, 26, "7. FANCIFUL NAME (If any)", _clean(detail.fanciful))

    right_w = RIGHT - SPLIT
    applicant = _applicant_block(detail)
    _field(
        c,
        SPLIT,
        830,
        right_w,
        86,
        "8. NAME AND ADDRESS OF APPLICANT AS SHOWN ON PLANT REGISTRY, BASIC PERMIT, "
        "OR BREWER'S NOTICE. INCLUDE APPROVED DBA OR TRADENAME IF USED ON THE LABEL "
        "(Required)",
        applicant,
        value_size=8.5,
    )
    _field(
        c,
        SPLIT,
        744,
        right_w,
        86,
        "8a. MAILING ADDRESS, IF DIFFERENT",
        _mailing_address(detail, applicant),
        value_size=8.5,
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
        value_size=8.0,
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
    _field(c, LEFT, 650, 124, 34, "12. PHONE NUMBER", _phone(detail.submitter_phone))
    _field(c, LEFT + 124, 650, 232, 34, "13. EMAIL ADDRESS")

    flags = _application_flags(detail)
    _field(c, 378, 650, RIGHT - 378, 94, "14. TYPE OF APPLICATION (Check applicable box(es))")
    _checkbox(c, 384, 726, flags["a"], "a. CERTIFICATE OF LABEL APPROVAL", size=6)
    _checkbox(c, 384, 712, flags["b"], "b. CERTIFICATE OF EXEMPTION FROM LABEL", size=6)
    cursor = _inline_value(
        c,
        394.5,
        703,
        'APPROVAL "For sale in ',
        _clean(detail.exemption_state) or _clean(detail.for_sale_in),
        placeholder="____",
    )
    c.setFont(BODY, 6)
    c.drawString(cursor + 2, 703, 'only"')
    _checkbox(c, 384, 688, flags["c"], "c. DISTINCTIVE LIQUOR BOTTLE APPROVAL.", size=6)
    c.setFont(BODY, 6)
    c.drawString(394.5, 679, "TOTAL BOTTLE CAPACITY BEFORE CLOSURE")
    _value_style(c, MONO_BOLD, 7.5)
    c.drawString(394.5, 670, _clean(detail.net_contents))
    _reset_style(c)
    _checkbox(c, 384, 658, flags["d"], "d. RESUBMISSION AFTER REJECTION", size=6)
    _inline_value(
        c,
        394.5,
        651,
        "OF TTB ID ",
        _clean(detail.resubmission_ttb_id),
        size=5.5,
    )

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

    _field(
        c,
        LEFT,
        486,
        110,
        26,
        "16. DATE OF APPLICATION",
        _date(detail.application_date),
        value_size=8.0,
    )
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
        # completed_date is the API's stand-in until the form scrape lands.
        _date(detail.issued_date) or _date(detail.approval_date),
        value_size=8.0,
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
    _field(
        c,
        LEFT,
        336,
        QUAL_BOX_W,
        QUAL_BOX_H,
        "QUALIFICATIONS",
        qualifications,
        value_size=QUAL_BOX_SIZE,
    )
    _field(
        c,
        LEFT + 458,
        336,
        RIGHT - LEFT - 458,
        74,
        "EXPIRATION DATE (If any)",
        _date(detail.expiration_date),
        value_size=8.0,
    )


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


def _draw_addendum_page(
    c: canvas.Canvas,
    rows: list[tuple[str, str]],
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

    marker_x = x + 6
    text_x = marker_x + stringWidth("00. ", MONO_BOLD, ADDENDUM_SIZE)
    cursor = y + h - 17 - ADDENDUM_SIZE
    _value_style(c, MONO_BOLD, ADDENDUM_SIZE)
    for marker, text in rows:
        if marker:
            c.drawString(marker_x, cursor, marker)
        if text:
            c.drawString(text_x, cursor, text)
        cursor -= ADDENDUM_LEAD
    _reset_style(c)


def render_f510031(detail: ColaDetail, images: list[LabelImage]) -> bytes:
    """Render the form for ``detail``, flowing ``images`` and overflow qualifications
    through their respective continuation pages."""
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

    row_width = CONT_W - 12
    # A single permit reads fine in item 2; a list of them does not, so it moves
    # to an addendum rather than being squeezed into the box or truncated.
    permit_pages: list[list[tuple[str, str]]] = []
    if len(detail.permits) > 1:
        permit_pages = _paginate_rows(_permit_rows(detail.permits, row_width), CONT_H)

    # Qualifications either fit the Part III box or all move to an addendum, so
    # a reader never has to stitch the list back together across two places.
    qual_text = _qualifications(detail)
    box_lines = _wrap(qual_text, MONO_BOLD, QUAL_BOX_SIZE, QUAL_BOX_W - 6)
    box_capacity = _field_value_lines(
        QUAL_BOX_H, QUAL_BOX_W, "QUALIFICATIONS", QUAL_BOX_SIZE
    )
    qual_pages: list[list[tuple[str, str]]] = []
    if len(box_lines) > box_capacity:
        rows = _qualification_rows(_qualification_texts(detail), row_width)
        qual_pages = _paginate_rows(rows, CONT_H)

    permit_start = len(pages) + 1
    qual_start = permit_start + len(permit_pages)
    total = qual_start + len(qual_pages) - 1

    permit_value = _clean(detail.permit_id) or _clean(detail.permit)
    if permit_pages:
        permit_value = _addendum_ref("permit", permit_start, len(permit_pages))
    if qual_pages:
        qual_text = _addendum_ref("qualifications", qual_start, len(qual_pages))

    _draw_application(c, detail, permit_value, qual_text)
    _draw_affix_page(c, pages[0], AFFIX_X, AFFIX_Y, AFFIX_W, AFFIX_H, AFFIX_TITLE)
    _draw_footer(c, detail, 1, total)

    page_number = 2
    for page_images in pages[1:]:
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
        _draw_footer(c, detail, page_number, total)
        page_number += 1

    addenda = [
        (title if i == 0 else f"{title} \u2014 continued", rows)
        for title, section in ((PERMIT_TITLE, permit_pages), (QUAL_TITLE, qual_pages))
        for i, rows in enumerate(section)
    ]
    for offset, (title, rows) in enumerate(addenda):
        c.showPage()
        height = min(CONT_H, len(rows) * ADDENDUM_LEAD + 21)
        _draw_addendum_page(
            c, rows, CONT_X, CONT_Y + CONT_H - height, CONT_W, height, title
        )
        _draw_footer(c, detail, permit_start + offset, total)

    c.showPage()
    c.save()
    return buf.getvalue()
