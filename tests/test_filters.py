"""Placeholder/parameter alignment for the COLA search filter builder.

A mismatch between the `%s` count and the bound parameter list only fails at
runtime, and only for the specific filter combination that drifted, so every
branch is exercised here.
"""
from __future__ import annotations

from datetime import date

import pytest

from src.api.routers.colas import SORTS, _build_filters, _default_date_from

FILTER_VALUES = {
    "q": "cabernet",
    "ttb_id": "26J087",
    "brand": "brand",
    "fanciful": "fanciful",
    "commodity": "Wine",
    "source": "Domestic",
    "origin": "California",
    "status": "APPROVED",
    "date_from": date(2020, 1, 1),
    "date_to": date(2024, 12, 31),
    "applicant": "applicant",
    "permit": "BWN-CA-1234",
    "permit_name": "winery",
    "permit_state": "ca",
    "permit_city": "napa",
    "submitter": "jane doe",
    "varietal": "merlot",
    "qualification": "qual",
    "label_text": "government warning",
}

EMPTY = {name: None for name in FILTER_VALUES}


def build(**overrides):
    return _build_filters(**(EMPTY | overrides))


def assert_aligned(where: str, params: list) -> None:
    assert where.count("%s") == len(params), where


@pytest.mark.parametrize("name", sorted(FILTER_VALUES))
def test_each_filter_binds_its_own_placeholders(name):
    where, params = build(**{name: FILTER_VALUES[name]})
    assert where.startswith("WHERE ")
    assert_aligned(where, params)


def test_all_filters_together():
    where, params = build(**FILTER_VALUES)
    assert_aligned(where, params)


def test_no_filters_produces_no_where_clause():
    where, params = build()
    assert where == ""
    assert params == []


def test_numeric_terms_add_a_cola_id_branch():
    where, params = build(q="12345")
    assert "cola_id = %s" in where
    assert 12345 in params
    assert_aligned(where, params)

    where, params = build(ttb_id="12345")
    assert "cola_id = %s" in where
    assert_aligned(where, params)


def test_non_numeric_terms_omit_the_cola_id_branch():
    where, _ = build(q="cabernet")
    assert "cola_id = %s" not in where


def test_identifier_terms_are_upper_cased_and_wildcards_escaped():
    _, params = build(permit="bwn-ca%1234")
    assert all("BWN-CA" in str(p) for p in params)
    assert r"BWN-CA\%1234%" in params


def test_label_text_probes_the_ocr_side_table():
    where, params = build(label_text="government warning")
    assert "cola_search_ocr" in where
    assert "ocr_tsv @@ websearch_to_tsquery" in where
    assert params == ["government warning"]


def test_every_sort_has_a_cola_id_tiebreaker():
    for order_by in SORTS.values():
        assert order_by.split(",")[-1].strip().startswith("cola_id ")


def test_default_date_from_uses_last_three_calendar_years():
    assert _default_date_from(date(2026, 8, 5)) == date(2024, 1, 1)
    assert _default_date_from(date(2027, 1, 1)) == date(2025, 1, 1)
