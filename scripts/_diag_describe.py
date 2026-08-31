"""Temporary diagnostic: exact vs ANN recall for a describe query."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

load_dotenv()

from api.db import close_pool, open_pool, transaction_cursor  # noqa: E402
from api.embedding import get_embedder  # noqa: E402
from api.vectors import to_pgvector  # noqa: E402

QUERY = os.environ.get("DIAG_Q", "a cartoon character in a hot tub")
TARGET = os.environ.get("DIAG_TARGET", "26212001000481")
LIMIT = 48
OVERFETCH = 6


async def main() -> None:
    await open_pool()
    vec = to_pgvector(await get_embedder().embed_text(QUERY))
    candidates = LIMIT * OVERFETCH

    async with transaction_cursor() as cur:
        await cur.execute("SET LOCAL statement_timeout TO '180s'")

        await cur.execute(
            "SELECT (image_feature_vector <=> %s::vector) AS dist FROM cola_images "
            "WHERE cola_id = %s AND image_feature_vector IS NOT NULL",
            [vec, TARGET],
        )
        target_dists = [round(float(r["dist"]), 4) for r in await cur.fetchall()]
        print(f"target {TARGET} distances: {target_dists}")

        await cur.execute("SET LOCAL hnsw.ef_search TO 1000")
        await cur.execute("SET LOCAL hnsw.iterative_scan TO relaxed_order")
        await cur.execute("SET LOCAL enable_seqscan TO off")
        await cur.execute(
            """--sql
            WITH knn AS (
              SELECT i.cola_id, (i.image_feature_vector <=> %s::vector) AS dist
              FROM cola_images i
              WHERE i.image_feature_vector IS NOT NULL
              ORDER BY i.image_feature_vector <=> %s::vector
              LIMIT %s
            ), best AS (
              SELECT DISTINCT ON (cola_id) cola_id, dist FROM knn ORDER BY cola_id, dist
            )
            SELECT cola_id, dist FROM best ORDER BY dist LIMIT %s
            """,
            [vec, vec, candidates, LIMIT],
        )
        ann = [(r["cola_id"], round(float(r["dist"]), 4)) for r in await cur.fetchall()]

        await cur.execute("SET LOCAL enable_seqscan TO on")
        await cur.execute("SET LOCAL enable_indexscan TO off")
        await cur.execute(
            """--sql
            SELECT DISTINCT ON (cola_id) cola_id,
                   (image_feature_vector <=> %s::vector) AS dist
            FROM cola_images
            WHERE image_feature_vector IS NOT NULL
            ORDER BY cola_id, dist
            """,
            [vec],
        )
        rows = [(r["cola_id"], float(r["dist"])) for r in await cur.fetchall()]

    rows.sort(key=lambda x: x[1])
    exact = [(c, round(d, 4)) for c, d in rows[:LIMIT]]

    ann_ids = {c for c, _ in ann}
    exact_ids = {c for c, _ in exact}
    print(f"\nindexed COLAs: {len(rows)}")
    print(f"ANN worst dist: {ann[-1][1]}   exact worst dist: {exact[-1][1]}")
    print(f"recall@{LIMIT}: {len(ann_ids & exact_ids)}/{LIMIT}")
    print(f"missed by ANN: {[(c, d) for c, d in exact if c not in ann_ids]}")
    for i, (c, d) in enumerate(rows, 1):
        if c == TARGET:
            print(f"exact rank of target: {i} (dist {round(d, 4)})")
            break
    print(f"target in ANN result: {TARGET in ann_ids}")

    await close_pool()


asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
