"""Pipeline coverage endpoint: row shaping, totals and caching."""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from api.main import app  # noqa: E402
from api.routers import coverage as coverage_router  # noqa: E402

PATH = "/api/coverage"


def _row(year: int, **overrides):
    return {
        "coverage_year": year,
        "api_cola_count": 100,
        "ingested_cola_count": 90,
        "detail_cola_count": 80,
        "image_cola_count": 70,
        "ocr_cola_count": 60,
        "embedding_cola_count": 50,
        "_loaded_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
    } | overrides


def _status(**overrides):
    return {
        "pending_count": 0,
        "oldest_pending_at": None,
        "searchable_count": 2_900_000,
        "label_text_count": 2_100_000,
    } | overrides


def _summary(cola_id: str, earliest_id: str, latest_id: str, **overrides):
    return {
        "earliest_id": earliest_id,
        "latest_id": latest_id,
        "cola_id": cola_id,
        "brand_name": "Test Brand",
        "completed_date": date(2026, 5, 6),
        "ct_commodity": "wine",
        "ct_source": "domestic",
    } | overrides


@pytest.fixture(autouse=True)
def clean():
    coverage_router.reset_cache()
    yield
    coverage_router.reset_cache()


@pytest.fixture
def client():
    return TestClient(app)


def stub(monkeypatch, rows, status=None, complete=()) -> list[str]:
    """Replace the database reads; returns the list of queries actually issued."""
    calls: list[str] = []

    async def fake_fetch_all(query, params=None):
        calls.append(query)
        # Two different reads share fetch_all, so dispatch on the query itself.
        return list(complete) if "bounds" in query else list(rows)

    async def fake_fetch_one(query, params=None):
        calls.append(query)
        return _status() if status is None else status

    monkeypatch.setattr(coverage_router, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(coverage_router, "fetch_one", fake_fetch_one)
    return calls


def test_rows_are_returned_in_query_order(client, monkeypatch):
    stub(monkeypatch, [_row(2025), _row(2024)])
    body = client.get(PATH).json()
    assert [y["year"] for y in body["years"]] == [2025, 2024]


def test_counts_are_summed_across_years(client, monkeypatch):
    stub(monkeypatch, [_row(2025), _row(2024)])
    totals = client.get(PATH).json()["totals"]
    assert totals["apiCount"] == 200
    assert totals["ingestedCount"] == 180
    assert totals["embeddingCount"] == 100


def test_partial_upstream_counts_do_not_produce_a_misleading_total(client, monkeypatch):
    """Summing only the years that reported would understate the upstream total."""
    stub(monkeypatch, [_row(2025), _row(2024, api_cola_count=None)])
    body = client.get(PATH).json()
    assert body["years"][1]["apiCount"] is None
    assert body["totals"]["apiCount"] is None


def test_missing_stage_counts_read_as_zero(client, monkeypatch):
    stub(monkeypatch, [_row(2025, ocr_cola_count=None)])
    assert client.get(PATH).json()["years"][0]["ocrCount"] == 0


def test_as_of_is_the_latest_refresh(client, monkeypatch):
    stub(
        monkeypatch,
        [
            _row(2025, _loaded_at=datetime(2026, 3, 4, tzinfo=timezone.utc)),
            _row(2024),
        ],
    )
    assert client.get(PATH).json()["asOf"].startswith("2026-03-04")


def test_no_rows_yields_empty_totals_rather_than_an_error(client, monkeypatch):
    stub(monkeypatch, [])
    body = client.get(PATH).json()
    assert body["years"] == []
    assert body["totals"]["ingestedCount"] == 0
    assert body["asOf"] is None


def test_search_index_status_is_reported(client, monkeypatch):
    stub(
        monkeypatch,
        [_row(2025)],
        status=_status(
            pending_count=42,
            oldest_pending_at=datetime(2026, 5, 6, tzinfo=timezone.utc),
        ),
    )
    search = client.get(PATH).json()["search"]
    assert search["pendingCount"] == 42
    assert search["oldestPendingAt"].startswith("2026-05-06")
    assert search["searchableCount"] == 2_900_000


def test_unanalysed_tables_report_no_estimate_rather_than_minus_one(client, monkeypatch):
    """pg_class.reltuples is -1 until the table has been analysed."""
    stub(monkeypatch, [_row(2025)], status=_status(searchable_count=-1))
    assert client.get(PATH).json()["search"]["searchableCount"] is None


def test_a_failed_status_query_does_not_blank_the_coverage_table(client, monkeypatch):
    stub(monkeypatch, [_row(2025)])

    async def boom(query, params=None):
        raise RuntimeError("relation does not exist")

    monkeypatch.setattr(coverage_router, "fetch_one", boom)
    body = client.get(PATH).json()
    assert body["search"] is None
    assert body["years"][0]["year"] == 2025


def test_repeat_requests_are_served_from_cache(client, monkeypatch):
    calls = stub(monkeypatch, [_row(2025)])
    client.get(PATH)
    client.get(PATH)
    # Coverage, status and complete-range reads, and nothing on the second request.
    assert len(calls) == 3


def test_complete_range_reports_both_ends(client, monkeypatch):
    stub(
        monkeypatch,
        [_row(2025)],
        complete=[
            _summary("1", "1", "2", completed_date=date(2024, 1, 2)),
            _summary("2", "1", "2", completed_date=date(2026, 3, 4)),
        ],
    )
    rng = client.get(PATH).json()["completeRange"]
    assert rng["earliest"]["id"] == "1"
    assert rng["earliest"]["approvalDate"] == "2024-01-02"
    assert rng["latest"]["id"] == "2"


def test_a_single_complete_record_is_both_ends_of_the_range(client, monkeypatch):
    stub(monkeypatch, [_row(2025)], complete=[_summary("7", "7", "7")])
    rng = client.get(PATH).json()["completeRange"]
    assert rng["earliest"]["id"] == "7"
    assert rng["latest"]["id"] == "7"


def test_no_complete_records_yields_an_empty_range_rather_than_an_error(client, monkeypatch):
    stub(monkeypatch, [_row(2025)], complete=[])
    rng = client.get(PATH).json()["completeRange"]
    assert rng["earliest"] is None
    assert rng["latest"] is None


def test_a_failed_range_query_does_not_blank_the_coverage_table(client, monkeypatch):
    stub(monkeypatch, [_row(2025)])

    async def fake_fetch_all(query, params=None):
        if "bounds" in query:
            raise RuntimeError("statement timeout")
        return [_row(2025)]

    monkeypatch.setattr(coverage_router, "fetch_all", fake_fetch_all)
    body = client.get(PATH).json()
    assert body["completeRange"] is None
    assert body["years"][0]["year"] == 2025
