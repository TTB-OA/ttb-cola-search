"""Layout maths and render robustness for the TTB F 5100.31 renderer.

The form is drawn with absolute coordinates, so the failure mode is a silent
exception on an unusual record rather than a wrong number. These exercise the
sparse, oversized and undecodable cases the registry actually produces.
"""
from __future__ import annotations

import io

import pytest
from PIL import Image
from pypdf import PdfReader

from src.api.forms.f510031 import (
    AFFIX_COLS,
    AFFIX_H,
    CONT_H,
    LabelImage,
    _application_flags,
    _fit_box,
    _grid_rows,
    _layout_images,
    _wrap,
    render_f510031,
)
from src.api.models import ColaDetail, PermitRef, Qualification

FIRST_CAPACITY = _grid_rows(AFFIX_H - 17) * AFFIX_COLS
PAGE_CAPACITY = _grid_rows(CONT_H - 17) * AFFIX_COLS


def jpeg(width: int = 400, height: int = 500) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 120, 60)).save(buf, format="JPEG")
    return buf.getvalue()


def label(name: str = "front.jpg", **overrides) -> LabelImage:
    fields = {
        "file_name": name,
        "img_type": "Brand (front) or keg collar",
        "face": "brand (front) or keg collar",
        "width_px": 400,
        "height_px": 500,
        "dimensions_txt": '3.5" x 4"',
        "data": jpeg(),
    }
    return LabelImage(**(fields | overrides))


def full_detail() -> ColaDetail:
    return ColaDetail(
        id="26087001000123",
        ttb_id="26087001000123",
        serial="26J087",
        brand="Estate Reserve",
        fanciful="Old Vine",
        category="Wine",
        class_type="RED TABLE WINE",
        origin="California",
        origin_group="Domestic",
        status="APPROVED",
        approval_date=__import__("datetime").date(2026, 3, 14),
        permit="BWN-CA-1234",
        permit_id="BWN-CA-1234",
        applicant="Example Winery LLC",
        submitter="Jane Doe",
        vendor_code="V-9911",
        net_contents="750.0000",
        mailing_address="PO Box 12, Napa CA 94558",
        application_type="CERTIFICATE OF LABEL APPROVAL",
        formula="12345",
        appellation="Napa Valley",
        grape_varietals=["Cabernet Sauvignon", "Merlot"],
        submitter_phone="707-555-0100",
        permits=[
            PermitRef(
                permit_id="BWN-CA-1234",
                primary=True,
                name="Example Winery LLC",
                address="1 Vineyard Way",
                city="Napa",
                state="CA",
                postal_code="94558",
                country="USA",
            )
        ],
        qualification_items=[
            Qualification(id=1, text="Label must be used as approved.", comment="")
        ],
    )


def page_count(pdf: bytes) -> int:
    return len(PdfReader(io.BytesIO(pdf)).pages)


# --- layout maths ----------------------------------------------------------
@pytest.mark.parametrize(
    "w,h,max_w,max_h",
    [(400, 500, 200, 200), (1000, 100, 200, 200), (50, 50, 200, 200)],
)
def test_fit_box_preserves_aspect_and_stays_inside(w, h, max_w, max_h):
    fw, fh = _fit_box(w, h, max_w, max_h)
    assert fw <= max_w + 1e-6 and fh <= max_h + 1e-6
    assert fw / fh == pytest.approx(w / h)


@pytest.mark.parametrize("w,h", [(0, 100), (100, 0), (-5, 5)])
def test_fit_box_rejects_degenerate_sizes(w, h):
    assert _fit_box(w, h, 200, 200) == (0.0, 0.0)


def test_no_images_still_produces_one_affix_page():
    assert _layout_images([], FIRST_CAPACITY, PAGE_CAPACITY) == [[]]


@pytest.mark.parametrize("count", [1, FIRST_CAPACITY])
def test_images_up_to_capacity_stay_on_page_one(count):
    pages = _layout_images([label()] * count, FIRST_CAPACITY, PAGE_CAPACITY)
    assert len(pages) == 1
    assert len(pages[0]) == count


def test_overflow_starts_a_continuation_page():
    pages = _layout_images(
        [label()] * (FIRST_CAPACITY + 1), FIRST_CAPACITY, PAGE_CAPACITY
    )
    assert len(pages) == 2
    assert [len(p) for p in pages] == [FIRST_CAPACITY, 1]


def test_every_image_is_placed_exactly_once():
    images = [label(f"{i}.jpg") for i in range(FIRST_CAPACITY + PAGE_CAPACITY + 3)]
    pages = _layout_images(images, FIRST_CAPACITY, PAGE_CAPACITY)
    assert [img for page in pages for img in page] == images


def test_wrap_breaks_a_word_too_long_for_the_column():
    lines = _wrap("A" * 200, "Helvetica", 8, 50)
    assert len(lines) > 1
    assert "".join(lines) == "A" * 200


@pytest.mark.parametrize(
    "text,expected",
    [
        ("CERTIFICATE OF LABEL APPROVAL", {"a"}),
        ("CERTIFICATE OF EXEMPTION FROM LABEL APPROVAL", {"b"}),
        ("CERTIFICATE OF LABEL APPROVAL | DISTINCTIVE LIQUOR BOTTLE", {"a", "c"}),
        ("RESUBMISSION AFTER REJECTION", {"d"}),
        ("", set()),
    ],
)
def test_application_type_selects_the_right_boxes(text, expected):
    detail = full_detail()
    detail.application_type = text
    flags = _application_flags(detail)
    assert {k for k, v in flags.items() if v} == expected


# --- rendering -------------------------------------------------------------
def test_renders_a_populated_record():
    pdf = render_f510031(full_detail(), [label("front.jpg"), label("back.jpg")])
    assert pdf.startswith(b"%PDF-")
    assert page_count(pdf) == 1


def test_renders_a_record_with_nothing_but_the_required_fields():
    bare = ColaDetail(id="1", ttb_id="1", category="Other", origin_group="Unknown")
    pdf = render_f510031(bare, [])
    assert pdf.startswith(b"%PDF-")
    assert page_count(pdf) == 1


def test_unreadable_blob_renders_a_placeholder_instead_of_raising():
    images = [label(data=None), label("bad.jpg", data=b"not an image")]
    assert render_f510031(full_detail(), images).startswith(b"%PDF-")


def test_extreme_aspect_ratios_render():
    images = [
        LabelImage(file_name="wide.jpg", data=jpeg(2000, 40)),
        LabelImage(file_name="tall.jpg", data=jpeg(40, 2000)),
    ]
    assert render_f510031(full_detail(), images).startswith(b"%PDF-")


def test_overflowing_images_add_pages():
    images = [label(f"{i}.jpg") for i in range(FIRST_CAPACITY + PAGE_CAPACITY + 1)]
    assert page_count(render_f510031(full_detail(), images)) == 3


def test_long_free_text_does_not_overflow_into_an_exception():
    detail = full_detail()
    detail.qualifications = "Qualification text. " * 200
    detail.qualification_items = []
    detail.mailing_address = "Very long address line " * 40
    assert render_f510031(detail, []).startswith(b"%PDF-")


def test_overflowing_qualifications_move_to_an_addendum_page():
    detail = full_detail()
    detail.qualification_items = [
        Qualification(id=i, text=f"Qualification number {i} applies to this label.", comment="")
        for i in range(1, 21)
    ]
    pdf = render_f510031(detail, [])
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 2
    assert "See qualifications addendum" in reader.pages[0].extract_text()
    addendum = reader.pages[1].extract_text()
    assert "Qualification number 1 applies" in addendum
    assert "Qualification number 20 applies" in addendum


def test_short_qualifications_stay_on_the_first_page():
    pdf = render_f510031(full_detail(), [])
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 1
    assert "Label must be used as approved" in reader.pages[0].extract_text()


def test_multiple_permits_move_to_an_addendum_page():
    detail = full_detail()
    detail.permits = [
        PermitRef(
            permit_id=f"BWN-CA-{1000 + i}",
            primary=i == 0,
            name=f"Example Winery {i} LLC",
            address=f"{100 + i} Vineyard Road",
            city="Napa",
            state="CA",
            postal_code="94558",
        )
        for i in range(4)
    ]
    reader = PdfReader(io.BytesIO(render_f510031(detail, [])))
    assert len(reader.pages) == 2
    assert "See permit addendum, page 2." in reader.pages[0].extract_text()
    addendum = reader.pages[1].extract_text()
    assert "BWN-CA-1000   (PRIMARY)" in addendum
    assert "BWN-CA-1003" in addendum


def test_single_permit_keeps_its_number_in_item_2():
    text = PdfReader(io.BytesIO(render_f510031(full_detail(), []))).pages[0].extract_text()
    assert "BWN-CA-1234" in text
    assert "permit addendum" not in text


def test_mailing_address_is_dropped_when_it_repeats_item_8():
    detail = full_detail()
    detail.permits = [
        PermitRef(
            permit_id="DSP-PA-20085",
            primary=True,
            name="Appalachian Spirits, LLC",
            address="6462 CARLISLE PIKE",
            city="Mechanicsburg",
            state="PA",
            postal_code="17050",
        )
    ]
    detail.mailing_address = "6462 CARLISLE PIKE , Mechanicsburg, PA 17050"
    text = PdfReader(io.BytesIO(render_f510031(detail, []))).pages[0].extract_text()
    assert text.count("6462 CARLISLE PIKE") == 1

    detail.mailing_address = "PO Box 12, Harrisburg, PA 17101"
    text = PdfReader(io.BytesIO(render_f510031(detail, []))).pages[0].extract_text()
    assert "PO Box 12, Harrisburg, PA 17101" in text
