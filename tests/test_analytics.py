"""Unit tests for analytics event shaping and privacy guarantees."""
from __future__ import annotations

import pytest

from src.api.analytics import (
    EVENT_BY_ROUTE,
    build_record,
    hash_identifier,
    route_key,
    session_id_from,
    shape_detail_event,
    shape_image_search_event,
    shape_search_event,
    shape_similar_event,
    size_bucket,
)

SESSION = "0f8fad5b-d9cb-469f-a165-70867728950e"


class FakeRequest:
    def __init__(self, headers=None, host="203.0.113.7"):
        self.headers = headers or {}
        self.client = type("C", (), {"host": host})()


def test_search_event_records_filter_names_not_values():
    attrs = shape_search_event(
        {"q": "napa cabernet", "brand": "Acme", "labelText": "sulfites", "commodity": "wine"}
    )
    assert attrs["filters_used"] == "q,brand,labelText,commodity"
    assert attrs["filter_count"] == 4
    assert "Acme" not in str(attrs)
    assert "sulfites" not in str(attrs)


def test_search_event_reduces_free_text_to_derived_attributes():
    attrs = shape_search_event({"q": "napa valley cabernet"})
    assert attrs["has_query"] is True
    assert attrs["query_length"] == 20
    assert attrs["term_count"] == 3
    assert "query_text" not in attrs


def test_search_event_captures_query_text_only_when_opted_in():
    attrs = shape_search_event({"q": "napa"}, capture_query_text=True)
    assert attrs["query_text"] == "napa"


def test_search_event_records_closed_vocabulary_values():
    attrs = shape_search_event({"commodity": "wine", "status": "Approved"})
    assert attrs["commodity"] == "wine"
    assert attrs["status"] == "Approved"


def test_search_event_defaults_match_the_api():
    attrs = shape_search_event({})
    assert attrs == {
        "filters_used": "",
        "filter_count": 0,
        "sort": "relevance",
        "page": 1,
        "page_size": 24,
        "facets_requested": True,
        "has_query": False,
        "query_length": 0,
        "term_count": 0,
    }


@pytest.mark.parametrize("page,expected", [("3", 3), ("", 1), ("abc", 1), (None, 1)])
def test_search_event_tolerates_bad_paging_values(page, expected):
    assert shape_search_event({"page": page})["page"] == expected


def test_blank_filters_are_not_counted_as_used():
    assert shape_search_event({"brand": "   ", "q": ""})["filter_count"] == 0


def test_similar_event_defaults():
    assert shape_similar_event({}) == {"scope": "all", "limit": 12}
    assert shape_similar_event({"scope": "member", "limit": "8"}) == {
        "scope": "member",
        "limit": 8,
    }


def test_detail_event_records_which_record_was_viewed():
    assert shape_detail_event({"cola_id": 26208001000457}) == {"cola_id": "26208001000457"}


def test_detail_event_omits_a_missing_id():
    assert shape_detail_event({}) == {}
    assert shape_detail_event({"cola_id": ""}) == {}


@pytest.mark.parametrize(
    "size,expected",
    [(None, "unknown"), (-1, "unknown"), (1024, "<250KB"), (500_000, "<1MB"), (9_000_000, ">=4MB")],
)
def test_size_bucket(size, expected):
    assert size_bucket(size) == expected


def test_image_search_event_strips_multipart_boundary():
    attrs = shape_image_search_event(2_000_000, "multipart/form-data; boundary=----abc")
    assert attrs == {"upload_size": "<4MB", "content_type": "multipart/form-data"}


def test_session_id_prefers_client_supplied_uuid():
    request = FakeRequest({"x-client-session": SESSION.upper()})
    assert session_id_from(request, trust_forwarded_for=True, salt="s") == SESSION


def test_malformed_session_header_falls_back_to_hashed_address():
    request = FakeRequest({"x-client-session": "not-a-uuid"})
    assert session_id_from(request, trust_forwarded_for=True, salt="s") == hash_identifier(
        "203.0.113.7", "s"
    )


def test_client_address_is_never_recorded_verbatim():
    request = FakeRequest({"x-forwarded-for": "198.51.100.4, 10.0.0.1"})
    session = session_id_from(request, trust_forwarded_for=True, salt="s")
    assert "198.51.100.4" not in session
    assert len(session) == 32


def test_salt_changes_the_hashed_session():
    request = FakeRequest()
    assert session_id_from(request, trust_forwarded_for=False, salt="a") != session_id_from(
        request, trust_forwarded_for=False, salt="b"
    )


def test_build_record_prefixes_keys_that_shadow_log_record_fields():
    record = build_record("view_mode_changed", {"module": "x", "name": "y", "view": "list"})
    assert record["prop_module"] == "x"
    assert record["prop_name"] == "y"
    assert record["view"] == "list"
    assert record["event"] == "view_mode_changed"
    assert record["microsoft.custom_event.name"] == "view_mode_changed"


def test_build_record_truncates_long_strings():
    assert len(build_record("e", {"v": "x" * 500})["v"]) == 200


def test_event_routes_use_route_templates_not_concrete_paths():
    for _, path in EVENT_BY_ROUTE:
        assert path.startswith("/")
        assert not path.endswith("/")


def test_route_key_normalises_prefixed_and_unprefixed_paths():
    assert route_key("GET", "/api/colas") == route_key("GET", "/colas")
    assert route_key("GET", "/api/colas") in EVENT_BY_ROUTE
