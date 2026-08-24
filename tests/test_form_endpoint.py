"""The form endpoint: wiring, headers, and failure modes.

The renderer itself is covered in test_form_pdf.py; these exercise the route —
that the detail 404 propagates, that unreadable blobs are tolerated, that the
image count is capped, and that the response is served as an inline PDF.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from api.main import app
from api.routers import colas as colas_router
from api.routers import forms as forms_router

PATH = "/api/colas/26087001000123/form.pdf"


def jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (300, 400), (180, 40, 40)).save(buf, format="JPEG")
    return buf.getvalue()


DETAIL_ROW = {
    "cola_id": 26087001000123,
    "ttb_id": "26087001000123",
    "brand_name": "Estate Reserve",
    "fanciful_name": "Old Vine",
    "ct_commodity": "W",
    "class_type_desc": "RED TABLE WINE",
    "origin_desc": "California",
    "status": "APPROVED",
}

IMAGE_ROWS = [
    {
        "file_name": "front.jpg",
        "img_type": "Brand (front) or keg collar",
        "width_px": 300,
        "height_px": 400,
        "dimensions_txt": '3" x 4"',
        "blob_name": "a/front.jpg",
    },
    {
        "file_name": "back.jpg",
        "img_type": "Back",
        "width_px": 300,
        "height_px": 400,
        "dimensions_txt": '3" x 4"',
        "blob_name": "a/back.jpg",
    },
]


@pytest.fixture
def client(monkeypatch):
    # The limiter is module state; a leaked bucket would 429 an unrelated test.
    forms_router._limiter = None

    async def fetch_one(query, params=None):
        return dict(DETAIL_ROW)

    async def fetch_all(query, params=None):
        return []

    monkeypatch.setattr(colas_router, "fetch_one", fetch_one)
    monkeypatch.setattr(colas_router, "fetch_all", fetch_all)
    monkeypatch.setattr(forms_router, "fetch_all", fetch_all)

    async def read_blob(blob_name):
        return jpeg()

    monkeypatch.setattr(forms_router, "read_blob", read_blob)
    return TestClient(app)


def with_images(monkeypatch, rows):
    async def fetch_all(query, params=None):
        limit = params[-1] if params else len(rows)
        return rows[:limit]

    monkeypatch.setattr(forms_router, "fetch_all", fetch_all)


def test_serves_an_inline_pdf(client):
    res = client.get(PATH)
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF-")


def test_filename_identifies_the_form_and_the_cola(client):
    disposition = client.get(PATH).headers["content-disposition"]
    assert disposition == 'inline; filename="TTB-F-5100-31-26087001000123.pdf"'


def test_response_is_privately_cached(client):
    assert client.get(PATH).headers["cache-control"] == "private, max-age=300"


def test_unknown_cola_is_a_404(client, monkeypatch):
    async def fetch_one(query, params=None):
        return None

    monkeypatch.setattr(colas_router, "fetch_one", fetch_one)
    res = client.get(PATH)
    assert res.status_code == 404
    assert res.json()["detail"] == "COLA not found"


def test_label_images_are_embedded(client, monkeypatch):
    with_images(monkeypatch, IMAGE_ROWS)
    assert client.get(PATH).content.startswith(b"%PDF-")


def test_a_failed_blob_read_does_not_fail_the_form(client, monkeypatch):
    with_images(monkeypatch, IMAGE_ROWS)

    async def read_blob(blob_name):
        if blob_name.endswith("back.jpg"):
            raise RuntimeError("blob is gone")
        return jpeg()

    monkeypatch.setattr(forms_router, "read_blob", read_blob)
    res = client.get(PATH)
    assert res.status_code == 200
    assert res.content.startswith(b"%PDF-")


def test_image_count_is_capped(client, monkeypatch):
    seen: list[list] = []

    async def fetch_all(query, params=None):
        seen.append(params)
        return []

    monkeypatch.setattr(forms_router, "fetch_all", fetch_all)
    client.get(PATH)
    assert seen[0] == [26087001000123, forms_router.MAX_FORM_IMAGES]


def test_over_the_limit_returns_429_with_retry_after(client, monkeypatch):
    monkeypatch.setattr(
        forms_router, "_limiter", forms_router.SlidingWindowLimiter(2, 60)
    )
    assert client.get(PATH).status_code == 200
    assert client.get(PATH).status_code == 200

    res = client.get(PATH)
    assert res.status_code == 429
    assert int(res.headers["retry-after"]) >= 1
