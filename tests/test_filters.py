"""Placeholder/parameter alignment for the COLA search filter builder.

A mismatch between the `%s` count and the bound parameter list only fails at
runtime, and only for the specific filter combination that drifted, so every
branch is exercised here.
"""
from __future__ import annotations

from datetime import date

import pytest

from src.api.routers.colas import SORTS, _build_filters, _order_by

FILTER_VALUES = {
    "q": "cabernet",
    "ttb_id": "26J087",
    "brand": "brand",
    "fanciful": "fanciful",
    "commodity": "Wine",
    "class_type": "TABLE RED WINE",
    "received_by": "Electronic submission (COLAs Online)",
    "source": "Domestic",
    "origin": "California",
    "status": "APPROVED",
    "date_from": date(2020, 1, 1),
    "date_to": date(2024, 12, 31),
    "applicant": "applicant",
    "business": "cedar hollow",
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


def test_terms_probe_cola_id_as_text():
    where, params = build(q="12345")
    assert "cola_id = %s" in where
    assert "12345" in params
    assert_aligned(where, params)

    where, params = build(ttb_id="12345")
    assert "cola_id = %s" in where
    assert "12345" in params
    assert_aligned(where, params)


def test_non_numeric_terms_still_probe_cola_id():
    # Ids carry A/B/C/D/$ suffixes and embedded spaces, so they are not numeric.
    where, params = build(q="26208001000457A")
    assert "cola_id = %s" in where
    assert "26208001000457A" in params

    where, params = build(ttb_id="26208001000457a")
    assert "cola_id = %s" in where
    assert "26208001000457A" in params
    assert_aligned(where, params)


def test_identifier_terms_are_upper_cased_and_wildcards_escaped():
    _, params = build(permit="bwn-ca%1234")
    assert all("BWN-CA" in str(p) for p in params)
    assert r"BWN-CA\%1234%" in params


def test_class_type_matches_the_description_or_the_code():
    where, params = build(class_type="  table red wine  ")
    assert "upper(class_type) = upper(%s)" in where
    assert "class_type_code = %s" in where
    assert params == ["table red wine", "table red wine"]


def test_class_type_is_independent_of_the_commodity_rollup():
    where, _ = build(class_type="TABLE RED WINE")
    assert "ct_commodity" not in where


def test_received_by_matches_the_description_or_the_code():
    where, params = build(received_by="es")
    assert "upper(received_description) = upper(%s)" in where
    assert "received_code = upper(%s)" in where
    assert params == ["es", "es"]


def test_label_text_probes_the_ocr_side_table():
    where, params = build(label_text="government warning")
    assert "cola_search_ocr" in where
    assert "ocr_tsv @@ websearch_to_tsquery" in where
    assert params == ["government warning"]


def test_business_matches_the_name_and_the_permit_number():
    where, params = build(business="cedar hollow")
    assert "applicant_name ILIKE %s" in where
    assert "permit_num LIKE %s" in where
    assert "permits @>" in where
    # Name half is a substring match; permit half is an upper-cased prefix.
    assert params[0] == "%cedar hollow%"
    assert params[1:] == ["CEDAR HOLLOW%", "CEDAR HOLLOW%", "CEDAR HOLLOW"]
    assert_aligned(where, params)


def test_business_uses_the_indexed_name_column():
    # primary_permit_name has no index and never diverges from applicant_name.
    where, _ = build(business="cedar hollow")
    assert "primary_permit_name" not in where


def test_permit_name_resolves_against_the_indexed_equivalent():
    where, params = build(permit_name="cedar hollow")
    assert where == "WHERE applicant_name ILIKE %s"
    assert params == ["%cedar hollow%"]


def test_q_also_matches_the_label_ocr():
    where, params = build(q="estate bottled")
    assert "cola_search_ocr" in where
    assert "ocr_tsv @@ websearch_to_tsquery" in where
    assert params[0] == "estate bottled"
    assert params[-1] == "estate bottled"
    assert_aligned(where, params)


def test_q_avoids_an_or_against_the_ocr_table():
    # An OR-ed EXISTS cannot be turned into a join and falls back to a per-row
    # subplan over a sequential scan of cola_search.
    where, _ = build(q="estate bottled")
    assert " OR " not in where
    assert "EXISTS" not in where
    assert "cola_id IN (" in where


def test_relevance_ranks_record_matches_above_ocr_only_matches():
    order_by, order_params = _order_by("relevance", "cabernet")
    assert order_by.startswith("(search_tsv @@ websearch_to_tsquery")
    assert order_by.endswith(SORTS["relevance"])
    assert order_params == ["cabernet"]


@pytest.mark.parametrize("sort,q", [("relevance", None), ("relevance", "   "), ("brand", "cabernet")])
def test_order_by_binds_nothing_without_a_ranked_term(sort, q):
    order_by, order_params = _order_by(sort, q)
    assert order_by == SORTS[sort]
    assert order_params == []


def test_unknown_sort_falls_back_to_relevance():
    assert _order_by("nonsense", None) == (SORTS["relevance"], [])


@pytest.mark.parametrize("sort", sorted(SORTS))
def test_order_by_placeholders_match_its_parameters(sort):
    order_by, order_params = _order_by(sort, "cabernet")
    assert order_by.count("%s") == len(order_params)


def test_every_sort_has_a_cola_id_tiebreaker():
    for order_by in SORTS.values():
        assert order_by.split(",")[-1].strip().startswith("cola_id ")
