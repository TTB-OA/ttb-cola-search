"""Temporary diagnostic: pairwise similarity among the matched images of a vector search."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

load_dotenv()

from api.db import close_pool, open_pool, transaction_cursor  # noqa: E402
from api.embedding import get_embedder  # noqa: E402
from api.routers.search import _nearest_by_vector, similar_colas  # noqa: E402
from api.vectors import to_pgvector  # noqa: E402

QUERY = os.environ.get("DIAG_Q", "")
SEED = os.environ.get("DIAG_SEED", "26212001000481")


async def main() -> None:
    await open_pool()
    try:
        if QUERY:
            vec = to_pgvector(await get_embedder().embed_text(QUERY))
            items = await _nearest_by_vector(vec, 48, None, None, min_candidates=5000)
        else:
            items = await similar_colas(SEED, limit=48, scope="all")
        groups = sum(i.duplicate_of is None for i in items)
        print(f"{len(items)} items, {groups} distinct artwork groups")
        ids = [i.id for i in items]
        files = [i.matched_file for i in items]
        async with transaction_cursor() as cur:
            await cur.execute(
                """--sql
                WITH m AS (
                  SELECT t.ord, i.image_feature_vector AS vec
                  FROM unnest(%s::text[], %s::text[]) WITH ORDINALITY AS t(cola_id, file_name, ord)
                  JOIN cola_images i ON i.cola_id = t.cola_id AND i.file_name = t.file_name
                )
                SELECT a.ord AS a, b.ord AS b, 1 - (a.vec <=> b.vec) AS sim
                FROM m a JOIN m b ON a.ord < b.ord
                ORDER BY sim DESC
                """,
                [ids, files],
            )
            pairs = await cur.fetchall()
        sims = [float(p["sim"]) for p in pairs]
        for cut in (0.99, 0.98, 0.97, 0.96, 0.95, 0.93, 0.9):
            print(f">= {cut}: {sum(s >= cut for s in sims)} pairs")
        print()
        for p in pairs[:60]:
            a, b = items[p["a"] - 1], items[p["b"] - 1]
            print(
                f"{float(p['sim']):.4f}  {a.brand!r:30.30} {a.fanciful!r:22.22} | "
                f"{b.brand!r:30.30} {b.fanciful!r:22.22}"
            )
    finally:
        await close_pool()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
