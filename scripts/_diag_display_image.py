"""One-off: calibrate a non-wine override for the display-image rule.

Samples non-wine COLAs whose visual-interest hero is NOT the front/keg image and
reports the front vs hero score gap and the front image's aspect ratio, so the
override threshold can be chosen from data rather than one example.
"""
import asyncio
import os
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

load_dotenv()
from api.db import close_pool, fetch_all, open_pool  # noqa: E402

SAMPLE_PCT = float(os.environ.get("DIAG_SAMPLE_PCT", "0.3"))

SQL = """--sql
WITH s AS (
    SELECT cola_id, ct_commodity, image_visual_interest_best_file_name AS hero
      FROM cola_search TABLESAMPLE SYSTEM (%(pct)s)
     WHERE coalesce(lower(ct_commodity), '') <> 'wine'
       AND image_visual_interest_best_file_name IS NOT NULL
),
imgs AS (
    SELECT s.cola_id, s.ct_commodity, s.hero,
           e ->> 'file_name' AS file_name,
           e ->> 'img_type' AS img_type,
           (e ->> 'visual_interest_score')::float8 AS score,
           (e ->> 'visual_interest_text_density_score')::float8 AS td,
           (e ->> 'width_px')::int AS w,
           (e ->> 'height_px')::int AS h
      FROM s
      JOIN cola_search_detail d ON d.cola_id = s.cola_id
      CROSS JOIN LATERAL jsonb_array_elements(
          CASE WHEN jsonb_typeof(d.images) = 'array' THEN d.images ELSE '[]'::jsonb END) e
)
SELECT cola_id, ct_commodity, hero,
       max(score) FILTER (WHERE strpos(upper(coalesce(img_type,'')), 'FRONT') > 0
                            OR strpos(upper(coalesce(img_type,'')), 'KEG') > 0) AS front_score,
       bool_or(td IS NOT NULL) FILTER (WHERE strpos(upper(coalesce(img_type,'')), 'FRONT') > 0
                            OR strpos(upper(coalesce(img_type,'')), 'KEG') > 0) AS front_ocr,
       max(score) FILTER (WHERE strpos(upper(coalesce(img_type,'')), 'BACK') > 0) AS back_score,
       max(score) FILTER (WHERE file_name = hero) AS hero_score,
       max(img_type) FILTER (WHERE file_name = hero) AS hero_type,
       max(greatest(w, h)::float8 / nullif(least(w, h), 0))
           FILTER (WHERE strpos(upper(coalesce(img_type,'')), 'FRONT') > 0
                      OR strpos(upper(coalesce(img_type,'')), 'KEG') > 0) AS front_aspect,
       max(w * h) FILTER (WHERE strpos(upper(coalesce(img_type,'')), 'FRONT') > 0
                            OR strpos(upper(coalesce(img_type,'')), 'KEG') > 0) AS front_area,
       max(w * h) FILTER (WHERE file_name = hero) AS hero_area,
       max(greatest(w, h)::float8 / nullif(least(w, h), 0)) FILTER (WHERE file_name = hero) AS hero_aspect,
       count(*) AS n_images
  FROM imgs
 GROUP BY 1, 2, 3
HAVING bool_or(strpos(upper(coalesce(img_type,'')), 'FRONT') > 0
               OR strpos(upper(coalesce(img_type,'')), 'KEG') > 0)
"""


async def main() -> None:
    await open_pool()
    rows = await fetch_all(SQL, {"pct": SAMPLE_PCT}, statement_timeout_ms=120_000, prepare=False)
    await close_pool()
    total = len(rows)
    hero_not_front = [
        r for r in rows
        if r["hero_type"] and "FRONT" not in r["hero_type"].upper() and "KEG" not in r["hero_type"].upper()
    ]
    print(f"sampled non-wine with a front image: {total}; hero is non-front: {len(hero_not_front)}")
    gaps = [r["hero_score"] - r["front_score"] for r in hero_not_front if r["front_score"] is not None]
    if gaps:
        qs = statistics.quantiles(gaps, n=20)
        print(f"hero-front gap p5/p25/p50/p75/p95: {qs[0]:.1f} {qs[4]:.1f} {qs[9]:.1f} {qs[14]:.1f} {qs[18]:.1f}")
    fronts = [r["front_score"] for r in hero_not_front if r["front_score"] is not None]
    if fronts:
        qs = statistics.quantiles(fronts, n=20)
        print(f"front score (hero non-front) p5/p25/p50/p75/p95: {qs[0]:.1f} {qs[4]:.1f} {qs[9]:.1f} {qs[14]:.1f} {qs[18]:.1f}")
    all_fronts = [r["front_score"] for r in rows if r["front_score"] is not None]
    if all_fronts:
        qs = statistics.quantiles(all_fronts, n=20)
        print(f"front score (all) p5/p25/p50/p75/p95: {qs[0]:.1f} {qs[4]:.1f} {qs[9]:.1f} {qs[14]:.1f} {qs[18]:.1f}")
    for lo, hi in [(0, 20), (20, 30), (30, 40), (40, 50), (50, 101)]:
        n = sum(1 for r in hero_not_front if r["front_score"] is not None and lo <= r["front_score"] < hi)
        print(f"  hero non-front, front score in [{lo},{hi}): {n}")
    for g in (10, 20, 25, 30, 35, 40):
        n = sum(1 for x in gaps if x >= g)
        print(f"  gap >= {g}: {n}")
    print("--- examples: hero non-front, largest gaps")
    for r in sorted(hero_not_front, key=lambda r: -((r["hero_score"] or 0) - (r["front_score"] or 0)))[:12]:
        print(f"  {r['cola_id']} {r['ct_commodity']}: front {r['front_score']} (aspect {r['front_aspect'] and round(r['front_aspect'],2)}) "
              f"hero {r['hero_type']} {r['hero_score']}")
    print("--- examples: hero non-front, smallest gaps")
    for r in sorted(hero_not_front, key=lambda r: ((r["hero_score"] or 0) - (r["front_score"] or 0)))[:8]:
        print(f"  {r['cola_id']} {r['ct_commodity']}: front {r['front_score']} (aspect {r['front_aspect'] and round(r['front_aspect'],2)}) "
              f"hero {r['hero_type']} {r['hero_score']}")
    print("--- hero is BACK, both scored: front score x hero-front gap")
    back_hero = [
        r for r in hero_not_front
        if "BACK" in (r["hero_type"] or "").upper() and r["front_score"] is not None and r["front_ocr"]
    ]
    print(f"  n={len(back_hero)} (of {len(hero_not_front)} hero non-front; front scored w/ OCR)")
    for lo, hi in [(0, 30), (30, 40), (40, 50), (50, 60), (60, 70), (70, 101)]:
        bucket = [r for r in back_hero if lo <= r["front_score"] < hi]
        gaps_b = [r["hero_score"] - r["front_score"] for r in bucket]
        med = statistics.median(gaps_b) if gaps_b else 0
        big = sum(1 for g in gaps_b if g >= 25)
        print(f"  front in [{lo},{hi}): n={len(bucket)} median gap {med:.1f} gap>=25: {big}")
    print("--- hero BACK candidates: front < 50 and gap >= 25 (ids for eyeballing)")
    cands = [r for r in back_hero if r["front_score"] < 50 and r["hero_score"] - r["front_score"] >= 25]
    print("  " + " ".join(r["cola_id"] for r in cands[:40]))
    print("--- hero BACK near-miss: front in [50,65) and gap >= 25")
    near = [r for r in back_hero if 50 <= r["front_score"] < 65 and r["hero_score"] - r["front_score"] >= 25]
    print("  " + " ".join(r["cola_id"] for r in near[:30]))
    aspects = [r["front_aspect"] for r in rows if r["front_aspect"]]
    qs = statistics.quantiles(aspects, n=100)
    print(f"front aspect (all) p50/p90/p95/p98/p99: {qs[49]:.2f} {qs[89]:.2f} {qs[94]:.2f} {qs[97]:.2f} {qs[98]:.2f}")
    for a in (3.0, 3.5, 4.0, 5.0):
        n_all = sum(1 for x in aspects if x >= a)
        n_hnf = sum(1 for r in hero_not_front if (r["front_aspect"] or 0) >= a)
        print(f"  front aspect >= {a}: all {n_all}, hero non-front {n_hnf}")
    print("--- strip fronts (aspect >= 3.5) where hero is non-front")
    for r in sorted(hero_not_front, key=lambda r: -(r["front_aspect"] or 0)):
        if (r["front_aspect"] or 0) < 3.5:
            break
        ratio = (r["hero_area"] or 0) / max(r["front_area"] or 1, 1)
        print(f"  {r['cola_id']} {r['ct_commodity']}: front {r['front_score']} aspect {r['front_aspect']:.2f} "
              f"hero {r['hero_type']} {r['hero_score']} aspect {r['hero_aspect'] and round(r['hero_aspect'],2)} area x{ratio:.1f}")
    print("--- strip fronts (aspect >= 3.5) where hero IS front")
    hero_front = [r for r in rows if r not in hero_not_front and (r["front_aspect"] or 0) >= 3.5]
    for r in sorted(hero_front, key=lambda r: -(r["front_aspect"] or 0))[:15]:
        print(f"  {r['cola_id']} {r['ct_commodity']}: front {r['front_score']} aspect {r['front_aspect']:.2f} n_images {r['n_images']}")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
