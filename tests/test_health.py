"""Health endpoint checks.

The endpoint exists to catch a class of failure that connectivity alone cannot
see: a connection that opens fine against a search_path holding none of the
relations the API reads. That combination once served HTTP 200 from /health
while every search returned 500.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from api.config import get_settings  # noqa: E402
from api.main import app  # noqa: E402
from api.routers import health as health_router  # noqa: E402

PATH = "/api/health"


@pytest.fixture(autouse=True)
def clean():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client():
    return TestClient(app)


def stub_db(monkeypatch, *, missing=(), raises=False):
    """Stand in for the probe query, returning the rows Postgres would."""

    async def fetch_one(_query, _params=None):
        if raises:
            raise RuntimeError("connection refused")
        return {
            "resolved_schema": "pcr-prod",
            "search_path": '"pcr-prod", public',
            "missing_relations": list(missing),
        }

    monkeypatch.setattr(health_router, "fetch_one", fetch_one)


def test_all_relations_resolve_is_ok(client, monkeypatch):
    stub_db(monkeypatch)
    body = client.get(PATH).json()

    assert body["status"] == "ok"
    assert body["database"]["connected"] is True
    assert body["database"]["missing_relations"] == []
    assert "error" not in body["database"]


def test_unreachable_database_is_degraded(client, monkeypatch):
    stub_db(monkeypatch, raises=True)
    body = client.get(PATH).json()

    assert body["status"] == "degraded"
    assert body["database"]["connected"] is False
    assert body["database"]["error"] == "connection_failed"


def test_connected_but_wrong_schema_is_degraded(client, monkeypatch):
    """The regression this endpoint was rewritten for: SELECT 1 would pass."""
    stub_db(monkeypatch, missing=["cola_search", "cola_search_ocr"])
    body = client.get(PATH).json()

    assert body["status"] == "degraded"
    assert body["database"]["connected"] is True
    assert body["database"]["error"] == "missing_relations"
    assert body["database"]["missing_relations"] == ["cola_search", "cola_search_ocr"]


def test_reports_configured_and_resolved_schema(client, monkeypatch):
    """Both are shown so a search_path mismatch is readable off the response."""
    stub_db(monkeypatch, missing=["cola_search"])
    monkeypatch.setattr(get_settings(), "postgres_schema", "pcr-dev", raising=False)

    database = client.get(PATH).json()["database"]

    assert database["configured_schema"] == "pcr-dev"
    assert database["resolved_schema"] == "pcr-prod"
    assert database["search_path"] == '"pcr-prod", public'


def test_probe_does_not_leak_driver_messages(client, monkeypatch):
    """The endpoint is public and unauthenticated."""
    stub_db(monkeypatch, raises=True)
    assert "connection refused" not in client.get(PATH).text


def test_required_relations_match_the_tables_queried():
    """Guards against a new hot table being added without probe coverage."""
    from api.mappers import COVERAGE_TABLE, OCR_TABLE, PERMIT_TABLE, SEARCH_TABLE

    assert set(health_router.REQUIRED_RELATIONS) == {
        SEARCH_TABLE,
        OCR_TABLE,
        COVERAGE_TABLE,
        PERMIT_TABLE,
    }
