"""Placeholder/parameter alignment for the COLA search statement builders.

A mismatch between the `%s` count and the bound parameter list only fails at
runtime, and only for the specific filter combination that drifted, so every
branch is exercised here.
"""
from __future__ import annotations

from datetime import date

import pytest

from src.api.config import get_settings
from src.api.routers.colas import (
    COUNT_CAP,
    FILTERED_ALIAS,
    KEYWORD_ALIAS,
    SORTS,
    _and,
    _build_filters,
    _keyword_source,
    _order_by,
    _term_params,
    aggregate_is_affordable,
    compose,
    only_status_filtered,
    record_match,
    term_match,
    ts_filter_sql,
    weighted_match,
)

FILTER_VALUES = {
    "ttb_id": "26J087",
    "brand": "brand",
    "fanciful": "fanciful",
    "commodity": "Wine",
    "class_type": "TABLE RED WINE",
    "received_by": "Electronic submission (COLAs Online)",
    "application_type": "DISTINCTIVE LIQUOR BOTTLE APPROVAL",
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


def assert_aligned(sql: str, params: list) -> None:
    assert sql.count("%s") == len(params), sql


@pytest.fixture
def weight_indexes(monkeypatch):
    """Run a test with the ts_filter expression indexes declared present."""
    monkeypatch.setattr(get_settings(), "search_weight_indexes", True)


@pytest.fixture
def weighted_form(monkeypatch):
    """Run a test with the expression indexes declared absent."""
    monkeypatch.setattr(get_settings(), "search_weight_indexes", False)


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


def test_ttb_id_probes_cola_id_as_text():
    where, params = build(ttb_id="12345")
    assert "cola_search.cola_id = %s" in where
    assert "12345" in params
    assert_aligned(where, params)

    # Ids carry A/B/C/D/$ suffixes and embedded spaces, so they are not numeric.
    where, params = build(ttb_id="26208001000457a")
    assert "26208001000457A" in params
    assert_aligned(where, params)


def test_class_type_matches_the_description_or_the_code():
    where, params = build(class_type="  table red wine  ")
    # Both arms line up with an index: upper(class_type) and class_type_code.
    assert "upper(class_type) = upper(%s)" in where
    assert "class_type_code = %s" in where
    assert params == ["table red wine", "table red wine"]


def test_class_type_is_independent_of_the_commodity_rollup():
    where, _ = build(class_type="TABLE RED WINE")
    assert "ct_commodity" not in where


def test_received_by_resolves_a_description_to_the_indexed_code():
    where, params = build(received_by="es")
    assert "received_code IN (SELECT received_code FROM ref_received_codes" in where
    assert "upper(description) = upper(%s)" in where
    assert "UNION SELECT upper(%s)" in where
    # The unindexed description column on cola_search is never compared.
    assert "received_description" not in where
    assert params == ["es", "es"]


def test_application_type_matches_one_component_of_the_multi_select():
    # "CERTIFICATE OF LABEL APPROVAL | DISTINCTIVE LIQUOR BOTTLE APPROVAL" has to
    # match on either half, so the stored string is split before comparison.
    where, params = build(application_type="  distinctive liquor bottle approval  ")
    assert "string_to_array(application_type, %s) @> ARRAY[upper(%s)]" in where
    assert params == [" | ", "distinctive liquor bottle approval"]


def test_application_type_does_not_match_a_bare_substring():
    where, _ = build(application_type="CERTIFICATE OF LABEL APPROVAL")
    assert "LIKE" not in where


def test_label_text_matches_the_label_weight_of_the_document(weighted_form):
    where, params = build(label_text="government warning")
    assert "cola_search_ocr" not in where
    assert "search_tsv @@" in where
    assert "':D'" in where
    assert params == ["government warning"]
    assert_aligned(where, params)


def test_label_text_uses_the_expression_index_when_present(weight_indexes):
    where, params = build(label_text="government warning")
    assert where == 'WHERE ts_filter(search_tsv, \'{d}\'::"char"[]) @@ websearch_to_tsquery(\'english\', %s)'
    assert params == ["government warning"]


def test_business_matches_the_name_and_the_permit_number():
    where, params = build(business="cedar hollow")
    assert "applicant_name ILIKE %s" in where
    assert "permit_num LIKE %s" in where
    assert "permit_ids @> ARRAY[%s::text]" in where
    # Name half is a substring match; permit half is an upper-cased prefix.
    assert params[0] == "%cedar hollow%"
    assert params[1:] == ["CEDAR HOLLOW%", "CEDAR HOLLOW%", "CEDAR HOLLOW"]
    assert_aligned(where, params)


def test_permit_match_stays_on_the_search_table():
    # An OR across two tables cannot use either index; the permit_ids GIN on
    # cola_search is what keeps this a BitmapOr.
    where, params = build(permit="bwn-ca%1234")
    assert "cola_search_detail" not in where
    assert " OR permit_ids @> ARRAY[%s::text]" in where
    assert params == [r"BWN-CA\%1234%", r"BWN-CA\%1234%", "BWN-CA%1234"]
    assert_aligned(where, params)


def test_permit_name_resolves_against_the_indexed_equivalent():
    where, params = build(permit_name="cedar hollow")
    assert where == "WHERE applicant_name ILIKE %s"
    assert params == ["%cedar hollow%"]


# --- Keyword sources ---------------------------------------------------------


def test_term_predicates_bind_the_term_and_the_id_columns():
    params = _term_params("  estate bottled ")
    assert params == ["estate bottled", *(["ESTATE BOTTLED"] * 4)]
    for predicate in (term_match(), record_match()):
        assert_aligned(predicate, params)
        assert "cola_search_ocr" not in predicate
        assert "search_tsv" in predicate


def test_record_match_restricts_lexemes_to_the_record_weights(weighted_form):
    assert "':ABC'" in record_match()
    assert "':ABC'" in weighted_match("ABC")
    assert "':ABC'" not in term_match()
    assert "':D'" in weighted_match("D")
    # regexp_replace over the rendered tsquery; the escape-aware lexeme class.
    assert "regexp_replace(websearch_to_tsquery('english', %s)::text" in record_match()
    assert "'''((?:[^'']|'''')*)'''" in record_match()


def test_record_match_uses_the_expression_index_when_present(weight_indexes):
    assert ts_filter_sql("ABC") == 'ts_filter(search_tsv, \'{a,b,c}\'::"char"[])'
    assert record_match().startswith(
        '(ts_filter(search_tsv, \'{a,b,c}\'::"char"[]) @@ websearch_to_tsquery(\'english\', %s)'
    )
    assert "regexp_replace" not in record_match()
    # The unrestricted match is the same either way.
    assert term_match().startswith("(search_tsv @@ websearch_to_tsquery('english', %s)")


def test_keyword_source_full_match_has_no_rank_column():
    source = _keyword_source("estate bottled")
    assert source.alias == KEYWORD_ALIAS
    assert "AS rec" not in source.body
    assert "':ABC'" not in source.body
    assert_aligned(source.body, source.params)


def test_keyword_source_ranked_computes_the_flag_once_per_match():
    source = _keyword_source("estate bottled", ranked=True)
    assert f"({weighted_match('ABC')}) AS rec" in source.body
    assert source.params[0] == "estate bottled"
    assert_aligned(source.body, source.params)


def test_keyword_source_record_only_uses_the_weighted_query(weighted_form):
    source = _keyword_source("estate bottled", record_only=True)
    assert "':ABC'" in source.body
    assert "AS rec" not in source.body
    assert source.params == ["estate bottled", *(["ESTATE BOTTLED"] * 4)]
    assert_aligned(source.body, source.params)


def test_keyword_source_carries_the_filters_inside_the_cte():
    # Filters are ANDed with the term inside the materialised set, after the
    # term parameters, so the planner cannot turn them into an index walk.
    where, where_params = build(commodity="Wine", status="Approved")
    source = _keyword_source("vodka", where, where_params, ranked=True)
    assert source.body.endswith(f"{where.removeprefix('WHERE ')}")
    assert " AND ct_commodity = %s AND status = %s" in source.body
    assert source.params == ["vodka", "vodka", *(["VODKA"] * 4), "wine", "Approved"]
    assert_aligned(source.body, source.params)


# --- Composition -------------------------------------------------------------


def test_compose_without_sources_reads_the_search_table_alone():
    assert compose([]) == ("", "cola_search", [])


def test_compose_materialises_every_source_and_joins_on_the_key():
    kw = _keyword_source("estate", ranked=True)
    with_sql, from_sql, params = compose([kw])
    assert with_sql.startswith(f"WITH {KEYWORD_ALIAS} AS MATERIALIZED (")
    assert from_sql == (
        f"cola_search JOIN {KEYWORD_ALIAS} ON {KEYWORD_ALIAS}.cola_id = cola_search.cola_id"
    )
    assert params == kw.params
    assert_aligned(with_sql, params)


def test_and_prepends_to_an_existing_or_empty_where():
    assert _and("", "x = 1") == "WHERE x = 1"
    assert _and("WHERE status = %s", "x = 1") == "WHERE x = 1 AND status = %s"


@pytest.mark.parametrize(
    "filters,expected",
    [
        ({}, True),
        ({"status": "Approved"}, True),
        ({"status": "Approved", "commodity": None, "brand": ""}, True),
        ({"status": "Approved", "commodity": "Wine"}, False),
        ({"status": "Approved", "permit": "BWN"}, False),
        ({"date_from": date(2020, 1, 1)}, False),
    ],
)
def test_only_status_filtered(filters, expected):
    assert only_status_filtered(filters) is expected


# --- Ordering ----------------------------------------------------------------


def test_relevance_ranks_record_matches_above_label_only_matches():
    order_by = _order_by("relevance", ranked=True)
    assert order_by.startswith(f"{KEYWORD_ALIAS}.rec DESC")
    assert order_by.endswith(SORTS["relevance"])
    assert "%s" not in order_by


@pytest.mark.parametrize("sort,ranked", [("relevance", False), ("brand", True)])
def test_order_by_ranks_only_relevance_with_a_term(sort, ranked):
    assert _order_by(sort, ranked) == SORTS[sort]


def test_unknown_sort_falls_back_to_relevance():
    assert _order_by("nonsense", ranked=False) == SORTS["relevance"]


def test_every_sort_has_a_qualified_cola_id_tiebreaker():
    # Qualified: the joined sources also expose cola_id.
    for order_by in SORTS.values():
        assert order_by.split(",")[-1].strip().startswith("cola_search.cola_id ")


# --- Aggregate affordability -------------------------------------------------


@pytest.mark.parametrize(
    "filters,expected",
    [
        ({}, True),
        ({"commodity": "Wine", "status": "Approved"}, True),
        # Now indexed upstream (trigram / expression btree).
        ({"varietal": "pinot"}, True),
        ({"permit_city": "napa", "permit_state": "CA"}, True),
        ({"class_type": "TABLE RED WINE"}, True),
        ({"received_by": "ES"}, True),
        # Still sequential scans.
        ({"qualification": "sulfite", "commodity": "Wine"}, False),
        ({"submitter": "smith"}, False),
        ({"submitter": "smith", "status": "Approved"}, False),
        ({"qualification": "sulfite", "q": "estate"}, True),
        ({"qualification": "sulfite", "brand": "stone"}, True),
        ({"qualification": "sulfite", "business": "cedar"}, True),
        ({"qualification": "sulfite", "varietal": "pinot"}, True),
        ({"qualification": "sulfite", "q": "   "}, False),
    ],
)
def test_aggregate_is_skipped_for_unindexed_filters_without_an_anchor(filters, expected):
    assert aggregate_is_affordable(**filters) is expected


# --- Label-text-only routing -------------------------------------------------


@pytest.mark.parametrize(
    "total,materialised",
    [(0, True), (45, True), (COUNT_CAP, True), (COUNT_CAP + 1, False)],
)
def test_label_text_only_materialises_a_set_under_the_count_cap(
    monkeypatch, total, materialised
):
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.api.routers import colas as colas_router

    statements: list[str] = []

    async def fake_fetch_all(sql, params=None, **kwargs):
        if "'total' AS dim" in sql:
            return [{"dim": "total", "value": None, "count": total}]
        statements.append(sql)
        assert sql.count("%s") == len(params)
        return []

    monkeypatch.setattr(colas_router, "fetch_all", fake_fetch_all)
    response = TestClient(app).get(
        "/api/colas", params={"labelText": "hangover", "status": "Approved"}
    )

    assert response.status_code == 200
    (rows_sql,) = statements
    assert (f"{FILTERED_ALIAS} AS MATERIALIZED" in rows_sql) is materialised
