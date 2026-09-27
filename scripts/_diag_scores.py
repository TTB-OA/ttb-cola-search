"""Temporary diagnostic: distribution of vector-search similarity scores.

Image->image (the "similar labels" panel) is measured from random seed images;
text->image (describe search) from DIAG_TEXTS. Each is compared against a random
pair baseline so the UI scale can be anchored on "unrelated" vs "same artwork".
"""
import asyncio
import os
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

load_dotenv()

from api.db import close_pool, open_pool, transaction_cursor  # noqa: E402
from api.embedding import get_embedder  # noqa: E402
from api.routers.search import _nearest_by_vector  # noqa: E402
from api.vectors import to_pgvector  # noqa: E402

N_SEEDS = int(os.environ.get("DIAG_SEEDS", "40"))
TEXTS = [
    t.strip()
    for t in os.environ.get(
        "DIAG_TEXTS",
        "Sasquatch eating pancakes|Cannabis leaf|red rooster on a black label|"
        "vineyard landscape at sunset|skull with roses|gold crown on white background|"
        "cartoon dog wearing sunglasses|mountain and pine trees|ocean waves and a lighthouse|"
        "minimalist black and white typography",
    ).split("|")
    if t.strip()
]
PCTS = (1, 5, 10, 25, 50, 75, 90, 95, 99)
RANK_BUCKETS = ((1, 1), (2, 5), (6, 12), (13, 24), (25, 48))


def pct(values: list[float], p: float) -> float:
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def summarize(label: str, values: list[float]) -> None:
    if not values:
        print(f"{label:28} (none)")
        return
    cells = " ".join(f"p{p}={pct(values, p):.3f}" for p in PCTS)
    print(f"{label:28} n={len(values):5} mean={statistics.fmean(values):.3f} {cells}")


def by_rank(runs: list[list[float]]) -> None:
    for lo, hi in RANK_BUCKETS:
        vals = [s for run in runs for r, s in enumerate(run, 1) if lo <= r <= hi]
        summarize(f"  rank {lo}-{hi}", vals)


async def sample_vectors(n: int) -> list[dict]:
    async with transaction_cursor() as cur:
        await cur.execute(
            """--sql
            SELECT cola_id, file_name, image_feature_vector::text AS vec
            FROM cola_images TABLESAMPLE SYSTEM (0.02)
            WHERE image_feature_vector IS NOT NULL
            ORDER BY random()
            LIMIT %s
            """,
            [n],
        )
        return list(await cur.fetchall())


async def baseline_image_pairs(sample: list[dict]) -> list[float]:
    ids = [r["cola_id"] for r in sample]
    files = [r["file_name"] for r in sample]
    async with transaction_cursor() as cur:
        await cur.execute(
            """--sql
            WITH m AS (
              SELECT t.ord, t.cola_id, i.image_feature_vector AS vec
              FROM unnest(%s::text[], %s::text[]) WITH ORDINALITY AS t(cola_id, file_name, ord)
              JOIN cola_images i ON i.cola_id = t.cola_id AND i.file_name = t.file_name
            )
            SELECT 1 - (a.vec <=> b.vec) AS sim
            FROM m a JOIN m b ON a.ord < b.ord AND a.cola_id <> b.cola_id
            """,
            [ids, files],
        )
        return [float(r["sim"]) for r in await cur.fetchall()]


async def baseline_text(vec: str, sample: list[dict]) -> list[float]:
    ids = [r["cola_id"] for r in sample]
    files = [r["file_name"] for r in sample]
    async with transaction_cursor() as cur:
        await cur.execute(
            """--sql
            SELECT 1 - (i.image_feature_vector <=> %s::vector) AS sim
            FROM unnest(%s::text[], %s::text[]) AS t(cola_id, file_name)
            JOIN cola_images i ON i.cola_id = t.cola_id AND i.file_name = t.file_name
            """,
            [vec, ids, files],
        )
        return [float(r["sim"]) for r in await cur.fetchall()]


async def main() -> None:
    await open_pool()
    try:
        sample = await sample_vectors(max(N_SEEDS, 300))
        print(f"sampled {len(sample)} random images\n")

        print("== IMAGE -> IMAGE ==")
        summarize("random pairs (baseline)", await baseline_image_pairs(sample))
        runs_all: list[list[float]] = []
        runs_distinct: list[list[float]] = []
        dup_scores: list[float] = []
        for seed in sample[:N_SEEDS]:
            items = await _nearest_by_vector(seed["vec"], 48, None, seed["cola_id"])
            runs_all.append([i.score for i in items if i.score is not None])
            runs_distinct.append(
                [i.score for i in items if i.score is not None and i.duplicate_of is None]
            )
            dup_scores += [i.score for i in items if i.duplicate_of is not None and i.score]
        summarize("top-48 (all rows)", [s for r in runs_all for s in r])
        summarize("top-48 (distinct leads)", [s for r in runs_distinct for s in r])
        by_rank(runs_distinct)
        summarize("folded duplicates", dup_scores)

        print("\n== TEXT -> IMAGE ==")
        embedder = get_embedder()
        base_all: list[float] = []
        text_runs: list[list[float]] = []
        for text in TEXTS:
            vec = to_pgvector(await embedder.embed_text(text))
            base = await baseline_text(vec, sample)
            base_all += base
            items = await _nearest_by_vector(vec, 48, None, None, min_candidates=5000)
            scores = [i.score for i in items if i.score is not None and i.duplicate_of is None]
            text_runs.append(scores)
            print(
                f"  {text[:40]:40} top1={scores[0]:.3f} top12={scores[min(11, len(scores) - 1)]:.3f} "
                f"top48={scores[-1]:.3f} | random median={statistics.median(base):.3f} "
                f"p99={pct(base, 99):.3f}"
            )
        summarize("random images (baseline)", base_all)
        summarize("top-48 (distinct leads)", [s for r in text_runs for s in r])
        by_rank(text_runs)
    finally:
        await close_pool()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
