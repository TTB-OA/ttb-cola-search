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


def stub(monkeypatch, rows) -> list[list]:
    """Replace the database read; returns the parameter lists actually bound."""
    calls: list[list] = []

    async def fake_fetch_all(query, params=None):
        calls.append(params)
        return list(rows)

    monkeypatch.setattr(suggest_router, "fetch_all", fake_fetch_all)
    return calls


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


def test_short_terms_never_reach_the_database(client, monkeypatch):
    calls = stub(monkeypatch, [_row("BWN-CA-1234")])
    assert client.get(PATH, params={"q": "b"}).json() == []
    assert client.get(PATH, params={"q": "   "}).json() == []
    assert calls == []


def test_id_branch_matches_on_an_upper_cased_prefix(client, monkeypatch):
    calls = stub(monkeypatch, [])
    client.get(PATH, params={"q": " bwn-ca "})
    assert calls[0][0] == "BWN-CA%"


def test_name_branch_matches_anywhere_and_keeps_the_typed_case(client, monkeypatch):
    calls = stub(monkeypatch, [])
    client.get(PATH, params={"q": "Cedar"})
    assert calls[0][1] == "%Cedar%"


def test_like_wildcards_in_the_term_are_escaped(client, monkeypatch):
    calls = stub(monkeypatch, [])
    client.get(PATH, params={"q": "bw%n_ca"})
    assert calls[0][0] == r"BW\%N\_CA%"
    assert calls[0][1] == r"%bw\%n\_ca%"


def test_limit_is_bound_and_capped(client, monkeypatch):
    calls = stub(monkeypatch, [])
    client.get(PATH, params={"q": "cedar", "limit": 25})
    assert calls[0][2] == 25
    assert client.get(PATH, params={"q": "cedar", "limit": 26}).status_code == 422
