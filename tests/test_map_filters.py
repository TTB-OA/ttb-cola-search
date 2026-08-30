"""Viewport filter builder for the map endpoints.

Same hazard as the search filters: a mismatch between the `%s` count and the
bound parameters only fails at runtime, for the one combination that drifted.
The bounding-box branches carry that risk twice over, since a viewport crossing
the antimeridian binds two envelopes instead of one.
"""
from __future__ import annotations

from datetime import date

import pytest

from src.api.routers.map import _cell_size, _wrap_longitude, build_map_filters

BBOX = (-125.0, 32.0, -114.0, 42.0)

FILTER_VALUES = {
    "commodity": "Wine",
    "source": "Domestic",
    "origin": "California",
    "class_type": "TABLE RED WINE",
    "date_from": date(2020, 1, 1),
    "date_to": date(2024, 12, 31),
}

EMPTY = {name: None for name in FILTER_VALUES}


def build(bbox=BBOX, role="primary_premise", **overrides):
    return build_map_filters(*bbox, role, **(EMPTY | overrides))


def assert_aligned(where: str, params: list) -> None:
    assert where.count("%s") == len(params), where


@pytest.mark.parametrize("name", sorted(FILTER_VALUES))
def test_each_filter_binds_its_own_placeholders(name):
    where, params = build(**{name: FILTER_VALUES[name]})
    assert where.startswith("WHERE ")
    assert_aligned(where, params)


def test_all_filters_together():
    assert_aligned(*build(**FILTER_VALUES))


def test_the_role_is_always_constrained():
    """Without it a COLA with several permits would be counted once per permit."""
    where, params = build()
    assert "location_role = %s" in where
    assert "primary_premise" in params


def test_a_viewport_crossing_the_antimeridian_binds_two_envelopes():
    where, params = build(bbox=(170.0, -40.0, -170.0, -30.0))
    assert where.count("ST_MakeEnvelope") == 2
    assert_aligned(where, params)


def test_a_viewport_wider_than_the_world_collapses_to_one_envelope():
    where, params = build(bbox=(-400.0, -80.0, 400.0, 80.0))
    assert where.count("ST_MakeEnvelope") == 1
    assert params[:4] == [-180.0, -80.0, 180.0, 80.0]


def test_latitudes_are_clamped_to_the_projection():
    """Panning past the poles is normal; asking PostGIS for latitude 95 is not."""
    _, params = build(bbox=(-10.0, -95.0, 10.0, 95.0))
    assert params[1] == -90.0
    assert params[3] == 90.0


def test_inverted_latitudes_are_ordered_rather_than_dropped():
    _, params = build(bbox=(-10.0, 42.0, 10.0, 32.0))
    assert params[1] == 32.0
    assert params[3] == 42.0


@pytest.mark.parametrize(
    "value,expected", [(190.0, -170.0), (-190.0, 170.0), (0.0, 0.0), (180.0, -180.0)]
)
def test_longitudes_fold_into_range(value, expected):
    assert _wrap_longitude(value) == pytest.approx(expected)


def test_bins_halve_with_each_zoom_step():
    """A bin has to stay the same size on screen, or the heat surface rescales."""
    assert _cell_size(5) == pytest.approx(_cell_size(4) / 2)


def test_the_grid_is_bounded_at_both_ends_of_the_zoom_range():
    assert _cell_size(-5) == _cell_size(0)
    assert _cell_size(30) == _cell_size(16)
