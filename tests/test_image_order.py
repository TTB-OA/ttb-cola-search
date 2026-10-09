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
    STRIP_ASPECT_RATIO,
    STRIP_FRONT_SCORE_GAP,
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


def test_display_order_sql_structure():
    order = image_display_order_sql("ci")
    assert "coalesce(lower(vi_hero.ct_commodity), '') = 'wine'" in order
    assert "image_visual_interest_best_file_name" in order
    assert "visual_interest_score DESC NULLS LAST" in order
    assert order.endswith("ci.file_name")


def test_display_order_without_rollup_drops_the_score_key():
    """The hot primary-image path skips the `images` jsonb, so it has no score."""
    order = image_display_order_sql("ci", out=None)
    assert "vi.visual_interest_score" not in order
    assert "image_visual_interest_best_file_name" in order
    assert "coalesce(lower(vi_hero.ct_commodity), '') = 'wine'" in order


def _simulate_sort(
    images: list[dict],
    commodity: str | None,
    hero_file: str | None,
    with_scores: bool = True,
) -> list[dict]:
    """Python simulation of `image_display_order_sql` sorting semantics."""
    by_name = {img["file_name"]: img for img in images}
    best = by_name.get(hero_file, {}).get("visual_interest_score")

    def tier(img, tr, is_wine):
        if is_wine:
            return 0
        w, h = img.get("width_px"), img.get("height_px")
        if tr == 0 and w and h and max(w, h) >= STRIP_ASPECT_RATIO * min(w, h):
            own = img.get("visual_interest_score")
            if own and best is not None and best - own >= STRIP_FRONT_SCORE_GAP:
                return 1
            return 0
        return tr

    def sort_key(img):
        fn = img["file_name"]
        tr = face_rank(image_face(img.get("img_type")))
        is_hero = 0 if (hero_file is not None and fn == hero_file) else 1
        score = img.get("visual_interest_score")
        score_key = -score if score is not None else float("inf")
        is_wine = (commodity or "").lower() == "wine"
        t = tier(img, tr, is_wine)
        if with_scores:
            return (t, is_hero, score_key, tr, fn)
        return (t, is_hero, tr, fn)

    return sorted(images, key=sort_key)


def test_wine_display_order_prefers_hero_over_front_type():
    images = [
        {"file_name": "front.jpg", "img_type": "Brand (front) or keg collar", "visual_interest_score": 60.0},
        {"file_name": "back.jpg", "img_type": "Back", "visual_interest_score": 85.0},
    ]
    ordered = _simulate_sort(images, commodity="wine", hero_file="back.jpg")
    assert ordered[0]["file_name"] == "back.jpg"


def test_wine_display_order_breaks_ties_by_score_and_type_rank():
    images = [
        {"file_name": "back.jpg", "img_type": "Back", "visual_interest_score": 40.0},
        {"file_name": "front.jpg", "img_type": "Brand (front) or keg collar", "visual_interest_score": 40.0},
    ]
    ordered = _simulate_sort(images, commodity="wine", hero_file=None)
    assert ordered[0]["file_name"] == "front.jpg"


def test_non_wine_display_order_prefers_front_type_over_hero_back():
    images = [
        {"file_name": "front.jpg", "img_type": "Brand (front) or keg collar", "visual_interest_score": 60.0},
        {"file_name": "back.jpg", "img_type": "Back", "visual_interest_score": 95.0},
    ]
    # For beer, front wins even if back is hero and has higher score
    ordered = _simulate_sort(images, commodity="beer", hero_file="back.jpg")
    assert ordered[0]["file_name"] == "front.jpg"

    # Same for distilled spirits
    ordered_spirits = _simulate_sort(images, commodity="distilled_spirits", hero_file="back.jpg")
    assert ordered_spirits[0]["file_name"] == "front.jpg"


def test_non_wine_display_order_breaks_type_ties_by_hero_and_score():
    images = [
        {"file_name": "front2.jpg", "img_type": "Brand (front) or keg collar", "visual_interest_score": 70.0},
        {"file_name": "front1.jpg", "img_type": "Brand (front) or keg collar", "visual_interest_score": 90.0},
    ]
    ordered = _simulate_sort(images, commodity="beer", hero_file="front1.jpg")
    assert ordered[0]["file_name"] == "front1.jpg"

    # Neither is hero: highest visual interest score breaks tie
    ordered_score = _simulate_sort(images, commodity="beer", hero_file=None)
    assert ordered_score[0]["file_name"] == "front1.jpg"


def test_unknown_commodity_defaults_to_type_rank_first():
    images = [
        {"file_name": "front.jpg", "img_type": "Brand (front) or keg collar", "visual_interest_score": 50.0},
        {"file_name": "back.jpg", "img_type": "Back", "visual_interest_score": 95.0},
    ]
    ordered_none = _simulate_sort(images, commodity=None, hero_file="back.jpg")
    assert ordered_none[0]["file_name"] == "front.jpg"

    ordered_unknown = _simulate_sort(images, commodity="unknown", hero_file="back.jpg")
    assert ordered_unknown[0]["file_name"] == "front.jpg"


# Real COLAs from prod: (cola_id, commodity, hero file, images, expected lead).
DISPLAY_CASES = [
    pytest.param(
        "26266001000201", "distilled_spirits", "back correct 58 27.jpg",
        [
            {"file_name": "brand correct 14 51.jpg", "img_type": "Brand (front) or keg collar",
             "width_px": 195, "height_px": 821, "visual_interest_score": 25.37},
            {"file_name": "back correct 58 27.jpg", "img_type": "Back",
             "width_px": 1739, "height_px": 784, "visual_interest_score": 62.55},
        ],
        "back correct 58 27.jpg",
        id="smith-wesson-strip-front-yields-to-logo-back",
    ),
    pytest.param(
        "08074001000126", "beer", "bl16bkBowl11st.jpg",
        [
            {"file_name": "bl16nkBowl11st.jpg", "img_type": "Brand (front) or keg collar",
             "width_px": 760, "height_px": 122, "visual_interest_score": 0.0},
            {"file_name": "bl16bkBowl11st.jpg", "img_type": "Back",
             "width_px": 334, "height_px": 209, "visual_interest_score": 70.1},
        ],
        "bl16nkBowl11st.jpg",
        id="bud-light-unscored-strip-front-stays",
    ),
    pytest.param(
        "16320001000093", "distilled_spirits", "BK563567B.jpg",
        [
            {"file_name": "JBMasterySingleBarrelACL.jpg", "img_type": "Brand (front) or keg collar",
             "width_px": 1152, "height_px": 648, "visual_interest_score": 69.71},
            {"file_name": "BK563567B.jpg", "img_type": "Back",
             "width_px": 650, "height_px": 394, "visual_interest_score": 70.05},
        ],
        "JBMasterySingleBarrelACL.jpg",
        id="jim-beam-narrow-score-gap-front-stays",
    ),
    pytest.param(
        "12206001000536", "beer", "OSA 507 oz Back.jpg",
        [
            {"file_name": "Zymaster Mag Face.jpg", "img_type": "Brand (front) or keg collar",
             "width_px": 809, "height_px": 601, "visual_interest_score": 31.75},
            {"file_name": "OSA 507 oz Back.jpg", "img_type": "Back",
             "width_px": 528, "height_px": 423, "visual_interest_score": 75.38},
        ],
        "Zymaster Mag Face.jpg",
        id="zymaster-square-front-stays-despite-gap",
    ),
    pytest.param(
        "14125001000054", "distilled_spirits", "Ivanabitch Cap.jpg",
        [
            {"file_name": "DSS_750ml Coconut_front.jpg", "img_type": "Brand (front) or keg collar",
             "width_px": 540, "height_px": 2200, "visual_interest_score": 62.07},
            {"file_name": "DSS_750ml Coconut_back.jpg", "img_type": "Back",
             "width_px": 543, "height_px": 2200, "visual_interest_score": 31.83},
            {"file_name": "Ivanabitch Cap.jpg", "img_type": "Other",
             "width_px": 369, "height_px": 369, "visual_interest_score": 100.0},
        ],
        "DSS_750ml Coconut_front.jpg",
        id="ivanabitch-demoted-front-still-beats-weaker-back",
    ),
]


@pytest.mark.parametrize("with_scores", [True, False], ids=["detail", "primary"])
@pytest.mark.parametrize("cola_id,commodity,hero,images,expected", DISPLAY_CASES)
def test_display_image_selection(cola_id, commodity, hero, images, expected, with_scores):
    ordered = _simulate_sort(images, commodity=commodity, hero_file=hero, with_scores=with_scores)
    assert ordered[0]["file_name"] == expected, cola_id


def test_display_order_sql_carries_strip_front_guard():
    for order in (image_display_order_sql("ci"), image_display_order_sql("ci", out=None)):
        assert f"{STRIP_ASPECT_RATIO} * least(ci.width_px, ci.height_px)" in order
        assert f">= {STRIP_FRONT_SCORE_GAP} THEN 1" in order
        assert "image_visual_interest_best_score" in order
    # The hot path has no `vi` join, so it reads its own score from the rollup.
    assert "cola_search_detail sd" in image_display_order_sql("ci", out=None)
def test_visual_interest_join_guards_a_non_array_rollup():
    """jsonb_array_elements raises on a scalar; NULL alone would be safe."""
    join = visual_interest_join_sql("ci")
    assert "jsonb_typeof(vi_detail.images) = 'array'" in join
    assert "LEFT JOIN LATERAL" in join
    assert "e ->> 'file_name' = ci.file_name" in join


def test_visual_interest_scores_come_from_the_detail_table():
    join = visual_interest_join_sql("ci")
    assert "LEFT JOIN cola_search_detail vi_detail ON vi_detail.cola_id = ci.cola_id" in join
    assert "vi_hero.images" not in join


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
