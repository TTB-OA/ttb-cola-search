"""Permit typeahead: term guards, LIKE escaping and response shaping."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from api.main import app  # noqa: E402
from api.routers import suggest as suggest_router  # noqa: E402

PATH = "/api/suggest/permits"


def _row(permit_id: str, **overrides):
    return {
        "permit_id": permit_id,
        "permit_name": "Cedar Hollow Winery",
        "city": "Napa",
        "state": "CA",
        "cola_count": 12,
    } | overrides


@pytest.fixture
def client():
    return TestClient(app)


def stub(monkeypatch, rows) -> list[tuple[str, list]]:
    """Replace the database read; returns the (sql, params) actually issued."""
    calls: list[tuple[str, list]] = []

    async def fake_fetch_all(query, params=None):
        calls.append((query, params))
        return list(rows)

    monkeypatch.setattr(suggest_router, "fetch_all", fake_fetch_all)
    return calls


def params_of(calls, i=0):
    return calls[i][1]


def test_rows_are_shaped_for_the_typeahead(client, monkeypatch):
    stub(monkeypatch, [_row("BWN-CA-1234")])
    body = client.get(PATH, params={"q": "bwn-ca"}).json()
    assert body == [
        {
            "permitId": "BWN-CA-1234",
            "name": "Cedar Hollow Winery",
            "city": "Napa",
            "state": "CA",
            "colaCount": 12,
        }
    ]


def test_a_permit_with_no_detail_filled_cola_still_suggests(client, monkeypatch):
    """Display fields are null until the detail pass reaches one of its COLAs."""
    stub(monkeypatch, [_row("BWN-CA-1234", permit_name=None, city=None, state=None)])
    body = client.get(PATH, params={"q": "bwn-ca"}).json()
    assert body[0] == {
        "permitId": "BWN-CA-1234",
        "name": None,
        "city": None,
        "state": None,
        "colaCount": 12,
    }


def test_short_terms_never_reach_the_database(client, monkeypatch):
    calls = stub(monkeypatch, [_row("BWN-CA-1234")])
    assert client.get(PATH, params={"q": "b"}).json() == []
    assert client.get(PATH, params={"q": "   "}).json() == []
    assert calls == []


def test_id_branch_matches_on_an_upper_cased_prefix(client, monkeypatch):
    calls = stub(monkeypatch, [])
    client.get(PATH, params={"q": " bwn-ca "})
    assert params_of(calls)[0] == "BWN-CA%"


def test_name_branch_matches_anywhere_and_keeps_the_typed_case(client, monkeypatch):
    calls = stub(monkeypatch, [])
    client.get(PATH, params={"q": "Cedar"})
    assert params_of(calls)[1] == "%Cedar%"


def test_two_character_terms_skip_the_unindexable_name_branch(client, monkeypatch):
    """pg_trgm cannot serve a term below three characters, so it stays on the id."""
    calls = stub(monkeypatch, [])
    client.get(PATH, params={"q": "bw"})

    sql, params = calls[0]
    assert "names_blob" not in sql
    assert params == ["BW%", 8]


def test_like_wildcards_in_the_term_are_escaped(client, monkeypatch):
    calls = stub(monkeypatch, [])
    client.get(PATH, params={"q": "bw%n_ca"})
    assert params_of(calls)[0] == r"BW\%N\_CA%"
    assert params_of(calls)[1] == r"%bw\%n\_ca%"


def test_limit_is_bound_and_capped(client, monkeypatch):
    calls = stub(monkeypatch, [])
    client.get(PATH, params={"q": "cedar", "limit": 25})
    assert params_of(calls)[2] == 25
    assert client.get(PATH, params={"q": "cedar", "limit": 26}).status_code == 422


def test_the_query_reads_the_materialised_permit_table(client, monkeypatch):
    """Never cola_permits: aggregating it per keystroke is what this replaced."""
    from api.mappers import PERMIT_TABLE

    calls = stub(monkeypatch, [])
    client.get(PATH, params={"q": "cedar"})

    sql = calls[0][0]
    assert PERMIT_TABLE in sql
    assert "cola_permits " not in sql
    assert "GROUP BY" not in sql
