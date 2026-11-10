"""CSV export of a text search: same filters as /colas, every row up to a cap."""
from __future__ import annotations

import csv
import io
from datetime import date

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.routers import colas as colas_router
from src.api.routers.colas import (
    EXPORT_COLUMNS,
    FILTERED_ALIAS,
    KEYWORD_ALIAS,
    csv_cell,
)

PATH = "/api/colas/export.csv"


def row(cola_id: str, **overrides):
    return {
        "cola_id": cola_id,
        "serial_num": "260001",
        "brand_name": "Cedar Hollow",
        "fanciful_name": "Reserve",
        "origin": "California",
        "ct_commodity": "wine",
        "ct_source": "domestic",
        "class_type": "TABLE RED WINE",
        "ttb_ct_description": "TABLE RED WINE",
        "status": "Approved",
        "completed_date": date(2026, 3, 4),
        "applicant_name": "Cedar Hollow Winery",
        "primary_permit_id": "BWN-CA-1234",
        "primary_permit_city_addr": "Napa",
        "primary_permit_state_addr": "CA",
        **overrides,
    }


@pytest.fixture
def statements(monkeypatch):
    """Record each statement and answer the rows query with `statements.rows`."""

    class Recorder(list):
        def __init__(self) -> None:
            super().__init__()
            self.rows: list[dict] = []

    recorded = Recorder()

    async def fake_fetch_all(sql, params=None, **kwargs):
        assert sql.count("%s") == len(params)
        recorded.append((sql, params))
        if "'total' AS dim" in sql:
            return [{"dim": "total", "value": None, "count": 3}]
        limit = params[-2]
        return recorded.rows[:limit]

    monkeypatch.setattr(colas_router, "fetch_all", fake_fetch_all)
    return recorded


def parse(response) -> list[list[str]]:
    text = response.content.decode("utf-8")
    assert text.startswith("﻿")
    return list(csv.reader(io.StringIO(text.removeprefix("﻿"))))


def test_export_returns_a_csv_attachment(statements):
    statements.rows = [row("26087001000123"), row("26087001000124", brand_name="Ça Va")]
    response = TestClient(app).get(PATH, params={"brand": "cedar", "status": "Approved"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"].startswith("attachment; filename=")
    assert response.headers["x-export-rows"] == "2"
    assert response.headers["x-export-truncated"] == "false"

    header, *body = parse(response)
    assert header == [h for h, _ in EXPORT_COLUMNS]
    assert [r[0] for r in body] == ['="26087001000123"', '="26087001000124"']
    record = dict(zip(header, body[1], strict=True))
    assert record["Brand Name"] == "Ça Va"
    assert record["Approval Date"] == "2026-03-04"
    assert record["Commodity"] == "Wine"


def test_export_is_not_taken_for_a_cola_id(statements):
    statements.rows = []
    response = TestClient(app).get(PATH)
    assert response.status_code == 200
    assert parse(response) == [[h for h, _ in EXPORT_COLUMNS]]


def test_export_reports_truncation_past_the_limit(statements):
    statements.rows = [row(str(n)) for n in range(4)]
    response = TestClient(app).get(PATH, params={"limit": 3})

    assert response.headers["x-export-rows"] == "3"
    assert response.headers["x-export-truncated"] == "true"
    assert len(parse(response)) == 4  # header + 3


def test_export_limit_is_capped():
    response = TestClient(app).get(PATH, params={"limit": colas_router.EXPORT_MAX_ROWS + 1})
    assert response.status_code == 422


def test_export_applies_the_search_filters(statements):
    statements.rows = []
    TestClient(app).get(PATH, params={"q": "vodka", "approvedWithin": 1, "sort": "brand"})
    sql, params = statements[-1]
    assert "brand_name ASC" in sql
    assert "completed_date >= %s" in sql
    assert "vodka" in params


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, ""),
        ("Cedar", "Cedar"),
        ("=HYPERLINK(\"x\")", "'=HYPERLINK(\"x\")"),
        ("+1", "'+1"),
        ("-196 Vodka", "'-196 Vodka"),
        ("@SUM", "'@SUM"),
        (date(2026, 1, 2), "2026-01-02"),
    ],
)
def test_cells_cannot_be_read_as_formulas(value, expected):
    assert csv_cell(value) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        # Leading zero of a 2000s id, and 14 digits Excel would show as 2.6E+13.
        ("08074001000126", '="08074001000126"'),
        ("26087001000123", '="26087001000123"'),
        # Ids with letters are already text to a spreadsheet.
        ("26J087", "26J087"),
        ("26208001000457A", "26208001000457A"),
        ("=1+1", "'=1+1"),
        (None, ""),
    ],
)
def test_identifier_cells_stay_text_in_a_spreadsheet(value, expected):
    assert csv_cell(value, identifier=True) == expected


def test_digit_only_values_outside_identifier_columns_are_untouched():
    assert csv_cell("12345") == "12345"


def test_serial_numbers_are_written_as_text(statements):
    statements.rows = [row("26087001000123", serial_num="080001")]
    header, record = parse(TestClient(app).get(PATH))
    assert dict(zip(header, record, strict=True))["Serial Number"] == '="080001"'


def rows_statements(statements) -> list[str]:
    return [sql for sql, _ in statements if "'total' AS dim" not in sql]


def test_a_keyword_export_never_walks_the_sort_index(statements):
    """The plain-predicate walk is for a page; 5,000 rows would run past the timeout."""
    statements.rows = []
    TestClient(app).get(PATH, params={"q": "vodka", "status": "Approved"})
    sql = rows_statements(statements)
    assert sql
    assert all(f"{KEYWORD_ALIAS} AS MATERIALIZED" in s for s in sql)


def test_a_keyword_page_still_walks_the_sort_index(statements):
    statements.rows = []
    TestClient(app).get("/api/colas", params={"q": "vodka", "status": "Approved"})
    first = rows_statements(statements)[0]
    assert "MATERIALIZED" not in first


def test_a_label_text_export_materialises_the_matching_set(statements):
    statements.rows = []
    TestClient(app).get(PATH, params={"labelText": "hangover", "status": "Approved"})
    # No count is needed to choose the plan, and no walk is attempted.
    assert all("'total' AS dim" not in sql for sql, _ in statements)
    (sql,) = rows_statements(statements)
    assert f"{FILTERED_ALIAS} AS MATERIALIZED" in sql
