"""The reference endpoint's per-value counts."""
from __future__ import annotations

import asyncio

from src.api.routers import reference as ref


def test_counts_are_served_and_class_counts_never_block(monkeypatch):
    class_count_calls = 0

    async def fake_fetch_all(sql, params=None, **kwargs):
        nonlocal class_count_calls
        if "FROM cola_grape_varietals" in sql:
            return [{"value": "Pinot noir", "n": 17155}]
        if "upper(class_type)" in sql:
            class_count_calls += 1
            return [{"value": "TABLE RED WINE", "n": 1435839}]
        if "ref_product_class_types" in sql:
            return [
                {"dim": "classType", "value": "TABLE RED WINE"},
                {"dim": "varietal", "value": "Pinot noir"},
            ]
        return []

    monkeypatch.setattr(ref, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(ref, "_cache", None)
    monkeypatch.setattr(ref, "_class_counts", None)
    monkeypatch.setattr(ref, "_class_count_task", None)

    async def scenario():
        first = await ref.reference()
        assert first.varietal_counts == {"Pinot noir": 17155}
        # The slow class/type pass runs off the request path.
        assert first.class_type_counts == {}

        await ref._class_count_task
        second = await ref.reference()
        assert second.class_type_counts == {"TABLE RED WINE": 1435839}
        assert second.model_dump(by_alias=True)["classTypeCounts"] == {"TABLE RED WINE": 1435839}

    asyncio.run(scenario())
    assert class_count_calls == 1
