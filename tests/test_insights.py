"""Tests for the unlisted usage dashboard endpoint."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from api import insights  # noqa: E402
from api.config import get_settings  # noqa: E402
from api.main import app  # noqa: E402
from api.routers import insights as insights_router  # noqa: E402

PATH = "/api/analytics/dashboard"


@pytest.fixture(autouse=True)
def clean():
    insights_router._limiter = None
    insights.reset_cache()
    get_settings.cache_clear()
    yield
    insights_router._limiter = None
    insights.reset_cache()
    get_settings.cache_clear()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def enabled(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "analytics_dashboard_enabled", True, raising=False)
    monkeypatch.setattr(settings, "log_analytics_workspace_id", "w0rkspace", raising=False)
    return settings


def _panels(names, rows=None):
    return {name: list(rows or []) for name in names}


# ---------------------------------------------------------------------------
# Gating
# ---------------------------------------------------------------------------
def test_disabled_returns_404_not_403(client):
    """404 so a disabled deployment does not advertise the feature."""
    response = client.get(PATH)
    assert response.status_code == 404


def test_disabled_does_not_query_log_analytics(client, monkeypatch):
    called = False

    async def boom(*_args, **_kwargs):
        nonlocal called
        called = True
        return {}, []

    monkeypatch.setattr(insights, "run_panels", boom)
    client.get(PATH)
    assert called is False


def test_unknown_range_is_rejected(client, enabled):
    assert client.get(PATH, params={"range": "5y"}).status_code == 422


def test_range_is_not_a_kql_injection_vector(client, enabled):
    assert client.get(PATH, params={"range": "7d | project *"}).status_code == 422


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
@pytest.fixture
def stub_panels(monkeypatch):
    """Stand in for Log Analytics with one representative row per panel."""
    calls: list[str] = []

    async def fake(_settings, range_key):
        calls.append(range_key)
        panels = {
            "totals": [
                {
                    "searches": 100,
                    "detailViews": 40,
                    "similarRequests": 5,
                    "imageSearches": 3,
                    "sessions": 25,
                }
            ],
            "usage_over_time": [
                {"TimeGenerated": "2026-01-01T00:00:00Z", "searches": 100, "detailViews": 40, "sessions": 25}
            ],
            "zero_results_over_time": [
                {"TimeGenerated": "2026-01-01T00:00:00Z", "searches": 100, "zero": 12}
            ],
            "filter_usage": [{"filter": "commodity", "count_": 60}],
            "paging_depth": [{"page": "1", "count_": 90}],
            "sort_usage": [{"sort": "relevance", "count_": 80}],
            "top_colas": [{"colaId": "123", "count_": 9}],
            "commodity_usage": [{"commodity": "Wine", "count_": 50}],
            "origin_usage": [{"origin": "California", "count_": 20}],
            "latency": [
                {"endpoint": "GET /api/colas", "requests": 100, "p50": 80.0, "p95": 420.0, "p99": 900.0}
            ],
            "reliability": [{"TimeGenerated": "2026-01-01T00:00:00Z", "total": 200, "failed": 4}],
            "status_codes": [{"code": "504", "count_": 4}],
            "image_search_over_time": [
                {"TimeGenerated": "2026-01-01T00:00:00Z", "performed": 3, "abandoned": 1, "stateLost": 0}
            ],
            "upload_sizes": [{"bucket": "<1MB", "count_": 3}],
        }
        return panels, []

    async def no_db(*_args, **_kwargs):
        raise RuntimeError("no database in tests")

    monkeypatch.setattr(insights, "run_panels", fake)
    monkeypatch.setattr(insights_router, "fetch_all", no_db)
    return calls


def test_returns_shaped_totals(client, enabled, stub_panels):
    body = client.get(PATH).json()

    assert body["range"] == "30d"
    assert body["cached"] is False
    assert body["totals"]["searches"] == 100
    assert body["totals"]["detailViews"] == 40
    assert body["totals"]["sessions"] == 25
    # 12 of 100 searches returned nothing.
    assert body["totals"]["zeroResultRate"] == 12.0
    # 4 of 200 requests failed.
    assert body["totals"]["failureRate"] == 2.0
    assert body["totals"]["p95Ms"] == 420.0


def test_returns_shaped_panels(client, enabled, stub_panels):
    panels = client.get(PATH).json()["panels"]

    assert panels["filterUsage"] == [{"label": "commodity", "count": 60}]
    assert panels["latency"][0]["endpoint"] == "GET /api/colas"
    assert panels["usageOverTime"][0]["values"]["searches"] == 100
    assert panels["imageSearchOverTime"][0]["values"]["abandoned"] == 1


def test_top_colas_survive_a_database_failure(client, enabled, stub_panels):
    """Names are an enrichment; losing them must not lose the ranking."""
    top = client.get(PATH).json()["panels"]["topColas"]
    assert top == [{"colaId": "123", "views": 9, "brandName": None, "origin": None}]


def test_failed_panels_are_reported_not_zeroed(client, enabled, monkeypatch):
    async def partial(_settings, _range):
        return {"totals": [{"searches": 7}]}, ["latency", "top_colas"]

    monkeypatch.setattr(insights, "run_panels", partial)
    body = client.get(PATH).json()

    assert body["totals"]["searches"] == 7
    assert set(body["unavailable"]) == {"latency", "top_colas"}


def test_query_failure_returns_503_not_500(client, enabled, monkeypatch):
    async def broken(*_args, **_kwargs):
        raise RuntimeError("workspace unreachable")

    monkeypatch.setattr(insights, "run_panels", broken)
    assert client.get(PATH).status_code == 503


# ---------------------------------------------------------------------------
# Caching and limits
# ---------------------------------------------------------------------------
def test_second_call_is_served_from_cache(client, enabled, stub_panels):
    first = client.get(PATH).json()
    second = client.get(PATH).json()

    assert first["cached"] is False
    assert second["cached"] is True
    # One Log Analytics round trip, not two.
    assert stub_panels == ["30d"]


def test_each_range_is_cached_separately(client, enabled, stub_panels):
    client.get(PATH, params={"range": "7d"})
    client.get(PATH, params={"range": "30d"})
    assert stub_panels == ["7d", "30d"]


def test_rate_limited_after_a_burst(client, enabled, stub_panels, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "analytics_dashboard_rate_limit", 2, raising=False)

    assert client.get(PATH).status_code == 200
    assert client.get(PATH).status_code == 200
    assert client.get(PATH).status_code == 429


# ---------------------------------------------------------------------------
# Query safety
# ---------------------------------------------------------------------------
def test_every_range_has_a_bucket_and_lookback():
    assert set(insights.RANGES) == set(insights._BUCKETS)
    assert insights.DEFAULT_RANGE in insights.RANGES


def test_queries_never_expose_raw_search_text():
    """capture_query_text is opt-in for KQL; it must never reach the page."""
    for bucket in insights._BUCKETS.values():
        for name, kql in insights._queries(bucket).items():
            assert "query_text" not in kql, name


def test_queries_contain_no_format_placeholders():
    """Nothing request-derived is interpolated beyond the fixed bucket width."""
    for bucket in insights._BUCKETS.values():
        for name, kql in insights._queries(bucket).items():
            assert "{" not in kql and "}" not in kql, name
