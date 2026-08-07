"""Label artwork ordering: upstream visual-interest score first, type rank as fallback.

`vw_colas` scores each image on aspect ratio, OCR text density and image-vs-text
embedding distance, and rolls the winner up to `cola_search`. When that score is
absent the old rule applies: brand/keg-collar first, back second, everything else
last. `cola_images.img_type` stores "Brand (front) or keg collar" as one value, so
the type rank has to match on substrings.
"""
from __future__ import annotations

import pytest

from src.api.mappers import (
    IMAGE_TYPE_RANK_SQL,
    SEARCH_TABLE,
    detail_from_rows,
    face_rank,
    hero_first_sql,
    image_display_order_sql,
    image_face,
    image_type_rank_sql,
    visual_interest_hero_join_sql,
    visual_interest_join_sql,
)

IMG_TYPES = [
    ("Brand (front) or keg collar", 0),
    ("Back", 1),
    ("Neck", 2),
    ("Strip", 2),
    ("Other", 2),
    (None, 2),
]

# Every fragment is interpolated into a psycopg query, where a bare '%' would be
# parsed as a placeholder.
SQL_FRAGMENTS = [
    IMAGE_TYPE_RANK_SQL,
    image_type_rank_sql("ci"),
    hero_first_sql("ci"),
    visual_interest_hero_join_sql("ci"),
    visual_interest_join_sql("ci"),
    image_display_order_sql("ci"),
    image_display_order_sql("ci", out=None),
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


@pytest.mark.parametrize("fragment", SQL_FRAGMENTS)
def test_fragments_carry_no_placeholder(fragment):
    assert "%" not in fragment


def test_type_rank_qualifies_every_column_reference():
    """An unqualified img_type is ambiguous once cola_search is joined in."""
    assert "ci.img_type" in image_type_rank_sql("ci")
    assert " img_type" not in image_type_rank_sql("ci")


def test_display_order_puts_hero_before_score_and_type_rank():
    order = image_display_order_sql("ci")
    hero = order.index("image_visual_interest_best_file_name")
    score = order.index("visual_interest_score DESC NULLS LAST")
    type_rank = order.index("strpos")
    file_name = order.rindex("ci.file_name")
    assert hero < score < type_rank < file_name


def test_display_order_without_rollup_drops_the_score_key():
    """The hot primary-image path skips the `images` jsonb, so it has no score."""
    order = image_display_order_sql("ci", out=None)
    assert "vi.visual_interest_score" not in order
    assert "image_visual_interest_best_file_name" in order
    assert "strpos" in order


def test_visual_interest_join_guards_a_non_array_rollup():
    """jsonb_array_elements raises on a scalar; NULL alone would be safe."""
    join = visual_interest_join_sql("ci")
    assert "jsonb_typeof(vi_hero.images) = 'array'" in join
    assert "LEFT JOIN LATERAL" in join
    assert "e ->> 'file_name' = ci.file_name" in join


def test_join_and_order_agree_on_the_cola_search_alias():
    """Mismatched defaults left ORDER BY referencing an unjoined alias."""
    join = visual_interest_join_sql("ci")
    order = image_display_order_sql("ci")
    alias = order.split("IS DISTINCT FROM ")[1].split(".")[0]
    assert f"LEFT JOIN {SEARCH_TABLE} {alias} " in join


def test_image_ref_carries_visual_interest():
    detail = detail_from_rows(
        {"cola_id": 1},
        [
            {
                "cola_id": 1,
                "file_name": "a.jpg",
                "img_type": "Back",
                "visual_interest_score": 71.25,
                "visual_interest_rank": 1,
            }
        ],
        [],
    )
    assert detail.images[0].visual_interest_score == pytest.approx(71.25)
    assert detail.images[0].visual_interest_rank == 1


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
