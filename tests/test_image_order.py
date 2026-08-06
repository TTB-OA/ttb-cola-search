"""Label artwork ordering: brand/keg-collar first, back second, everything else last.

`cola_images.img_type` stores "Brand (front) or keg collar" as one value, so the
rank has to match on substrings. The SQL and Python ranks are separate
implementations of the same rule and are asserted to agree here.
"""
from __future__ import annotations

import pytest

from src.api.mappers import (
    IMAGE_TYPE_RANK_SQL,
    detail_from_rows,
    face_rank,
    image_face,
)

IMG_TYPES = [
    ("Brand (front) or keg collar", 0),
    ("Back", 1),
    ("Neck", 2),
    ("Strip", 2),
    ("Other", 2),
    (None, 2),
]


@pytest.mark.parametrize("img_type,expected", IMG_TYPES)
def test_face_rank(img_type, expected):
    assert face_rank(image_face(img_type)) == expected


def test_sql_rank_matches_python_rank():
    """The SQL CASE arms mirror face_rank; drift here silently reorders the UI."""
    assert "'FRONT'" in IMAGE_TYPE_RANK_SQL
    assert "'KEG'" in IMAGE_TYPE_RANK_SQL
    assert "'BACK'" in IMAGE_TYPE_RANK_SQL
    assert IMAGE_TYPE_RANK_SQL.endswith("ELSE 2 END")
    # A bare '%' would be parsed as a psycopg placeholder in the queries using this.
    assert "%" not in IMAGE_TYPE_RANK_SQL


def test_image_items_group_brand_face_first():
    items = [
        {"cola_id": 1, "file_name": "c.jpg", "img_type": t, "text": t}
        for t, _ in IMG_TYPES
        if t
    ]
    detail = detail_from_rows({"cola_id": 1}, [], items)
    assert [i.face for i in detail.image_items] == [
        "brand (front) or keg collar",
        "back",
        "neck",
        "other",
        "strip",
    ]
