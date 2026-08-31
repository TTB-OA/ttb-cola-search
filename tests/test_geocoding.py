"""Geocoding status on the detail record, and ranged basemap reads.

Both are pure functions over values the pipeline supplies, so they are tested
without a database or a storage account.
"""
from __future__ import annotations

import pytest

from src.api.blob import RangeNotSatisfiable, _parse_range
from src.api.mappers import geocoding_state, location_from_row
from src.api.models import GeoLocation

SIZE = 1000


def _location(**overrides) -> GeoLocation:
    return location_from_row(
        {
            "location_role": "primary_premise",
            "source_key": "BWN-CA-1234",
            "permit_id": "BWN-CA-1234",
            "permit_name": "Cedar Hollow",
            "latitude": 38.5,
            "longitude": -122.4,
            "geolocation_quality": "rooftop",
            "geolocation_provider": "census",
            "geolocation_method": "Rooftop",
        }
        | overrides
    )


# --- geocoding status -------------------------------------------------------
def test_a_located_cola_reports_located():
    assert geocoding_state([_location()], 1, 1) == "located"


def test_an_address_never_queued_is_not_the_same_as_one_that_failed():
    assert geocoding_state([], 0, 0) == "not_processed"


def test_an_address_awaiting_a_provider_is_pending():
    assert geocoding_state([], 2, 0) == "pending"


def test_an_address_a_provider_could_not_place_is_a_miss_not_a_backlog():
    """Every observation was answered, and none produced a point."""
    assert geocoding_state([], 2, 2) == "no_match"


def test_missing_counts_read_as_never_queued():
    """The geolocation tables may not exist in an environment at all."""
    assert geocoding_state([], None, None) == "not_processed"


def test_a_point_carries_the_provenance_that_qualifies_it():
    """A centroid and a rooftop match are both points; only quality says which."""
    point = _location(location_role="product_origin", geolocation_quality="centroid")
    assert point.role == "product_origin"
    assert point.quality == "centroid"
    assert (point.lat, point.lng) == (38.5, -122.4)


# --- ranged reads -----------------------------------------------------------
def test_no_range_header_means_the_whole_blob():
    assert _parse_range(None, SIZE) is None


def test_a_closed_range_is_inclusive_of_both_ends():
    assert _parse_range("bytes=0-99", SIZE) == (0, 99)


def test_an_open_range_runs_to_the_end_of_the_blob():
    assert _parse_range("bytes=900-", SIZE) == (900, SIZE - 1)


def test_a_suffix_range_counts_back_from_the_end():
    """PMTiles reads its header this way before it knows the archive layout."""
    assert _parse_range("bytes=-16", SIZE) == (SIZE - 16, SIZE - 1)


def test_a_range_running_past_the_end_is_truncated_rather_than_refused():
    assert _parse_range("bytes=900-5000", SIZE) == (900, SIZE - 1)


@pytest.mark.parametrize("header", ["bytes=1000-1100", "bytes=500-400", "bytes=-0"])
def test_a_range_outside_the_blob_is_unsatisfiable(header):
    with pytest.raises(RangeNotSatisfiable):
        _parse_range(header, SIZE)


@pytest.mark.parametrize(
    "header", ["items=0-99", "bytes=0-99,200-299", "bytes=abc-def", "bytes=0"]
)
def test_ranges_that_cannot_be_honoured_fall_back_to_the_whole_blob(header):
    assert _parse_range(header, SIZE) is None
