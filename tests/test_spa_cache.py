"""Cache headers on the served SPA.

index.html names the content-hashed bundle, so a browser that caches it is
pinned to the deploy that produced it. Serving it with no Cache-Control lets
browsers apply heuristic freshness, which shipped a deploy that users could not
see until a hard refresh.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from api.config import get_settings  # noqa: E402
from api.main import create_app  # noqa: E402

IMMUTABLE = "public, max-age=31536000, immutable"


@pytest.fixture
def client(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html></html>")
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log(1)")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    monkeypatch.setenv("SPA_DIR", str(tmp_path))
    get_settings.cache_clear()
    yield TestClient(create_app())
    get_settings.cache_clear()


@pytest.mark.parametrize("path", ["/", "/results", "/colas/26J087"])
def test_index_and_client_routes_must_revalidate(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"


def test_hashed_assets_are_immutable(client):
    r = client.get("/assets/index-abc123.js")
    assert r.status_code == 200
    assert r.headers["cache-control"] == IMMUTABLE


def test_unhashed_files_are_not_cached_forever(client):
    r = client.get("/favicon.svg")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"


def test_a_missing_asset_404s_rather_than_falling_back_to_index(client):
    # The fallback would return HTML for a .js request and break module parsing.
    assert client.get("/assets/gone.js").status_code == 404
