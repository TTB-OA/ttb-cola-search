"""Map endpoint behaviour: modes, caps, validation and degraded states."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from psycopg.errors import UndefinedTable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from api.main import app  # noqa: E402
from api.routers import map as map_router  # noqa: E402

POINTS = "/api/map/points"
AREA = "/api/map/area"
VIEWPORT = {"west": -125, "south": 32, "east": -114, "north": 42}


@pytest.fixture(autouse=True)
def clean():
    map_router.reset_limiter()
    yield
    map_router.reset_limiter()


@pytest.fixture
def client():
    return TestClient(app)


def stub(monkeypatch, rows=(), one=None) -> list[tuple[str, list]]:
    """Replace the database reads; returns the (query, params) pairs issued."""
    calls: list[tuple[str, list]] = []

    async def fake_fetch_all(query, params=None):
        calls.append((query, list(params or [])))
        return list(rows(query) if callable(rows) else rows)

    async def fake_fetch_one(query, params=None):
        calls.append((query, list(params or [])))
        return one

    monkeypatch.setattr(map_router, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(map_router, "fetch_one", fake_fetch_one)
    return calls


def bound(calls) -> list:
    """Parameters bound by the map queries, ignoring the capability probe."""
    return [p for query, params in calls if "information_schema" not in query for p in params]


def _bin(gx: int, gy: int, n: int, scanned: int = 3):
    return {"gx": gx, "gy": gy, "n": n, "scanned": scanned}


def _point(cola_id: str, **overrides):
    return {
        "cola_id": cola_id,
        "latitude": 38.5,
        "longitude": -122.4,
        "ct_commodity": "wine",
        "origin": "California",
        "completed_date": date(2026, 5, 6),
        "best_image_file_name": "front.jpg",
        "brand_name": "Test Brand",
    } | overrides


# --- heat mode --------------------------------------------------------------
def test_bins_are_returned_at_the_centre_of_their_cell(client, monkeypatch):
    """A bin drawn at the cell corner would sit south-west of its own records."""
    stub(monkeypatch, [_bin(0, 0, 3)])
    body = client.get(POINTS, params={**VIEWPORT, "zoom": 0}).json()

    cell = map_router._cell_size(0)
    assert body["bins"][0]["lng"] == pytest.approx(cell / 2)
    assert body["bins"][0]["lat"] == pytest.approx(cell / 2)


def test_the_total_counts_records_not_bins(client, monkeypatch):
    stub(monkeypatch, [_bin(0, 0, 7, scanned=9), _bin(1, 0, 2, scanned=9)])
    body = client.get(POINTS, params=VIEWPORT).json()
    assert body["total"] == 9
    assert body["totalIsCapped"] is False


def test_hitting_the_scan_cap_reports_a_floor(client, monkeypatch):
    cap = map_router.get_settings().map_scan_cap
    stub(monkeypatch, [_bin(0, 0, cap + 1, scanned=cap + 1)])
    body = client.get(POINTS, params=VIEWPORT).json()
    assert body["total"] == cap
    assert body["totalIsCapped"] is True


def test_an_empty_viewport_is_not_an_error(client, monkeypatch):
    stub(monkeypatch, [])
    body = client.get(POINTS, params=VIEWPORT).json()
    assert body["bins"] == []
    assert body["total"] == 0


def test_the_scan_is_capped_in_sql_not_after_the_fact(client, monkeypatch):
    calls = stub(monkeypatch, [])
    client.get(POINTS, params=VIEWPORT)
    assert any("LIMIT" in query for query, _p in calls)
    assert map_router.get_settings().map_scan_cap + 1 in bound(calls)


# --- image mode -------------------------------------------------------------
def test_image_mode_returns_pins_with_thumbnails(client, monkeypatch):
    stub(monkeypatch, [_point("26J087")])
    body = client.get(POINTS, params={**VIEWPORT, "mode": "image"}).json()

    point = body["points"][0]
    assert body["mode"] == "image"
    assert point["brand"] == "Test Brand"
    assert point["category"] == "Wine"
    assert point["thumbUrl"] == "/api/colas/26J087/images/front.jpg"


def test_a_pin_without_a_label_has_no_thumbnail_rather_than_a_broken_one(
    client, monkeypatch
):
    stub(monkeypatch, [_point("26J087", best_image_file_name=None)])
    body = client.get(POINTS, params={**VIEWPORT, "mode": "image"}).json()
    assert body["points"][0]["thumbUrl"] is None


def test_image_mode_is_capped_so_the_map_stays_readable(client, monkeypatch):
    calls = stub(monkeypatch, [])
    client.get(POINTS, params={**VIEWPORT, "mode": "image"})
    assert map_router.get_settings().map_image_point_cap in bound(calls)


# --- validation -------------------------------------------------------------
@pytest.mark.parametrize("params", [{"mode": "satellite"}, {"role": "warehouse"}])
def test_unknown_modes_and_roles_are_rejected(client, monkeypatch, params):
    stub(monkeypatch, [])
    assert client.get(POINTS, params={**VIEWPORT, **params}).status_code == 400


def test_a_missing_viewport_is_rejected(client, monkeypatch):
    stub(monkeypatch, [])
    assert client.get(POINTS, params={"west": -125, "south": 32}).status_code == 422


def test_the_role_reaches_the_query(client, monkeypatch):
    calls = stub(monkeypatch, [])
    client.get(POINTS, params={**VIEWPORT, "role": "product_origin"})
    assert "product_origin" in bound(calls)


# --- degraded states --------------------------------------------------------
def test_an_unbuilt_map_surface_says_so_rather_than_reporting_an_empty_world(
    client, monkeypatch
):
    async def missing(query, params=None):
        raise UndefinedTable('relation "cola_map_search" does not exist')

    monkeypatch.setattr(map_router, "fetch_all", missing)
    response = client.get(POINTS, params=VIEWPORT)
    assert response.status_code == 503
    assert "not been built" in response.json()["detail"]


def test_repeated_panning_is_rate_limited(client, monkeypatch):
    stub(monkeypatch, [])
    monkeypatch.setattr(map_router, "_limiter", map_router.SlidingWindowLimiter(2, 60))

    codes = [client.get(POINTS, params=VIEWPORT).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


# --- varietal capability gate -----------------------------------------------
def test_varietal_is_reported_unavailable_when_the_column_is_missing(client, monkeypatch):
    stub(monkeypatch, [], one=None)
    body = client.get(POINTS, params=VIEWPORT).json()
    assert body["varietalAvailable"] is False


def test_a_varietal_filter_the_surface_cannot_apply_is_refused(client, monkeypatch):
    """Ignoring it would return unfiltered results under a filtered heading."""
    stub(monkeypatch, [], one=None)
    response = client.get(POINTS, params={**VIEWPORT, "varietal": "Cabernet"})
    assert response.status_code == 400
    assert "varietal" in response.json()["detail"].lower()


def test_a_varietal_filter_is_applied_where_the_column_exists(client, monkeypatch):
    calls = stub(monkeypatch, [], one={"ok": 1})
    response = client.get(POINTS, params={**VIEWPORT, "varietal": "Cabernet"})

    assert response.status_code == 200
    assert response.json()["varietalAvailable"] is True
    assert "%Cabernet%" in bound(calls)


def test_the_column_probe_runs_once_rather_than_per_viewport(client, monkeypatch):
    """Panning would otherwise add a catalogue query to every frame."""
    calls = stub(monkeypatch, [], one={"ok": 1})
    for _ in range(3):
        client.get(POINTS, params=VIEWPORT)
    assert sum("information_schema" in q for q, _p in calls) == 1


# --- area drill-in ----------------------------------------------------------
def _area_rows(query):
    if "dim" in query:
        return [
            {"dim": "commodity", "value": "wine", "count": 5},
            {"dim": "source", "value": "domestic", "count": 5},
            {"dim": "origin", "value": "California", "count": 4},
            {"dim": "origin", "value": None, "count": 1},
        ]
    return [{"cola_id": "26J087", "brand_name": "Test Brand", "ct_commodity": "wine"}]


def test_an_area_summary_labels_its_codes(client, monkeypatch):
    stub(monkeypatch, _area_rows, one={"n": 5})
    body = client.get(AREA, params=VIEWPORT).json()

    assert body["total"] == 5
    assert body["commodity"][0] == {"value": "Wine", "count": 5}
    assert body["source"][0]["value"] == "Domestic"
    assert body["items"][0]["id"] == "26J087"


def test_an_area_summary_drops_unlabelled_buckets(client, monkeypatch):
    stub(monkeypatch, _area_rows, one={"n": 5})
    origins = client.get(AREA, params=VIEWPORT).json()["origin"]
    assert [o["value"] for o in origins] == ["California"]


def test_an_area_summary_reports_a_capped_total_as_a_floor(client, monkeypatch):
    cap = map_router.get_settings().map_scan_cap
    stub(monkeypatch, _area_rows, one={"n": cap + 1})
    body = client.get(AREA, params=VIEWPORT).json()
    assert body["total"] == cap
    assert body["totalIsCapped"] is True
