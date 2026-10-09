"""The image proxy re-encodes TIFF labels, which only Safari can display."""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from api.main import app
from api.routers import images as images_router

PATH = "/api/colas/12336001000052/images/front.tif"


def encoded(fmt: str, mode: str = "RGB") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (40, 60)).save(buf, format=fmt)
    return buf.getvalue()


@pytest.fixture
def serve(monkeypatch):
    async def fetch_one(query, params=None):
        return {"file_name": "front.tif", "blob_name": "a/front.tif", "blob_url": None}

    monkeypatch.setattr(images_router, "fetch_one", fetch_one)

    def _serve(data: bytes, content_type: str):
        async def stream_blob(blob_name):
            async def chunks():
                yield data[:10]
                yield data[10:]

            return chunks(), content_type

        monkeypatch.setattr(images_router, "stream_blob", stream_blob)
        return TestClient(app).get(PATH)

    return _serve


@pytest.mark.parametrize("mode", ["RGB", "RGBA", "L", "1", "CMYK"])
def test_tiff_is_served_as_jpeg(serve, mode):
    res = serve(encoded("TIFF", mode), "image/tiff")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/jpeg"
    assert res.headers["cache-control"] == "public, max-age=86400"
    with Image.open(io.BytesIO(res.content)) as im:
        assert im.format == "JPEG"
        assert im.size == (40, 60)


def test_undecodable_tiff_falls_back_to_the_original(serve):
    res = serve(b"MM\x00*garbage", "image/tiff")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/tiff"
    assert res.content == b"MM\x00*garbage"


def test_browser_formats_pass_through(serve):
    data = encoded("PNG")
    res = serve(data, "image/png")
    assert res.headers["content-type"] == "image/png"
    assert res.content == data
