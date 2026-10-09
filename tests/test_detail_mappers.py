"""Values the detail mapper derives or cleans rather than passing through."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from api.mappers import compact_address, received_date_from_ttb_id


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        (", ,", None),
        (" ,  , ", None),
        ("123 MAIN ST , LOUISVILLE, KY 40210", "123 MAIN ST, LOUISVILLE, KY 40210"),
        ("  , , KY 40210", "KY 40210"),
        ("1 A ST, , CA 90001, USA", "1 A ST, CA 90001, USA"),
    ],
)
def test_compact_address_drops_empty_parts(raw, expected):
    assert compact_address(raw) == expected


@pytest.mark.parametrize(
    ("ttb_id", "expected"),
    [
        ("12336001000052", date(2012, 12, 1)),
        ("09217001000287", date(2009, 8, 5)),
        ("79333000000001", date(1979, 11, 29)),
        ("99001000000001", date(1999, 1, 1)),
        ("24366001000001", date(2024, 12, 31)),
        ("26087001000123A", date(2026, 3, 28)),
    ],
)
def test_prefix_is_year_and_day_of_year(ttb_id, expected):
    assert received_date_from_ttb_id(ttb_id) == expected


@pytest.mark.parametrize("ttb_id", [None, "", "1234", "AB123001000001", "23366001000001", "12000001000001"])
def test_unparseable_ids_have_no_date(ttb_id):
    assert received_date_from_ttb_id(ttb_id) is None
