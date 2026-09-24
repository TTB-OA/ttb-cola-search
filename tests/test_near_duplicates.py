"""Near-duplicate folding for vector search results."""
from __future__ import annotations

from src.api.models import ColaSummary
from src.api.routers.search import group_near_duplicates


def _items(n: int) -> list[ColaSummary]:
    return [
        ColaSummary(id=f"c{i}", ttb_id=f"c{i}", category="wine", origin_group="domestic")
        for i in range(n)
    ]


def test_no_pairs_keeps_the_first_limit_items():
    out = group_near_duplicates(_items(5), [], limit=3)
    assert [i.id for i in out] == ["c0", "c1", "c2"]
    assert all(i.duplicate_of is None for i in out)


def test_duplicates_ride_along_with_their_lead_past_the_limit():
    out = group_near_duplicates(_items(5), [(0, 1), (0, 4)], limit=2)
    assert [(i.id, i.duplicate_of) for i in out] == [
        ("c0", None),
        ("c1", "c0"),
        ("c2", None),
        ("c4", "c0"),
    ]


def test_membership_is_against_the_lead_not_a_chain():
    # c1 resembles c0 and c2 resembles c1, but c2 is not close to the lead.
    out = group_near_duplicates(_items(3), [(0, 1), (1, 2)], limit=3)
    assert [(i.id, i.duplicate_of) for i in out] == [
        ("c0", None),
        ("c1", "c0"),
        ("c2", None),
    ]


def test_duplicate_of_a_dropped_item_is_dropped_too():
    out = group_near_duplicates(_items(4), [(1, 3)], limit=1)
    assert [i.id for i in out] == ["c0"]
