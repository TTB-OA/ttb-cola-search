"""One-off: run the real display-order SQL against prod for known COLAs.

Each case names the COLA and the image that should lead. Both sort variants
(`out='vi'` as used by the detail page, `out=None` as used by the primary
thumbnail and similar-COLA seed) are checked.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

load_dotenv()
from api.db import close_pool, fetch_all, open_pool  # noqa: E402
from api.mappers import (  # noqa: E402
    image_display_order_sql,
    visible_image_sql,
    visual_interest_hero_join_sql,
    visual_interest_join_sql,
)

# (cola_id, expected lead file_name, why)
CASES = [
    ("26266001000201", "back correct 58 27.jpg", "spirits: 195x821 text strip front, logo-only back hero (+37)"),
    ("19308001000607", "375ml circle general back label.jpg", "spirits: 1968x333 strip front, barrel back hero (+33)"),
    ("24092001000267", None, "spirits: 2880x321 strip front, bathtub back hero (+39)"),
    ("08074001000126", "bl16nkBowl11st.jpg", "beer: Bud Light strip front never OCR'd -> stays"),
    ("09272000000014", "publicViewImage_label_02.jpg", "spirits: Don Q bottle drawing never OCR'd -> stays"),
    ("16320001000093", None, "spirits: Jim Beam strip front, back hero by +0.3 -> stays"),
    ("12206001000536", None, "beer: Zymaster square front, back hero by +43 -> stays"),
    ("14125001000054", "DSS_750ml Coconut_front.jpg", "spirits: 540x2200 front, cap hero (Other) -> front stays"),
    ("22094001000234", "Brand 1Top.jpg", "spirits: two fronts, one strip; square front leads"),
    ("23139001000398", None, "wine: hero leads regardless of type"),
]


async def lead(cola_id: str, scored: bool) -> list[dict]:
    if scored:
        join = visual_interest_join_sql("ci")
        extra = ", vi.visual_interest_score"
        order = image_display_order_sql("ci")
    else:
        join = visual_interest_hero_join_sql("ci")
        extra = ""
        order = image_display_order_sql("ci", out=None)
    return await fetch_all(
        f"SELECT ci.file_name, ci.img_type, ci.width_px, ci.height_px{extra} "
        f"FROM cola_images ci {join} "
        f"WHERE ci.cola_id = %s AND {visible_image_sql('ci')} ORDER BY {order}",
        [cola_id],
    )


async def main() -> None:
    await open_pool()
    failures = 0
    for cola_id, expected, why in CASES:
        scored = await lead(cola_id, True)
        hot = await lead(cola_id, False)
        s_lead = scored[0]["file_name"] if scored else None
        h_lead = hot[0]["file_name"] if hot else None
        # Ties among same-tier fronts break by score on the detail path only.
        ok = (expected is None or s_lead == expected) and (s_lead == h_lead or expected is None)
        failures += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {cola_id} {why}")
        print(f"      detail lead: {s_lead!r}  primary lead: {h_lead!r}  expected: {expected!r}")
        for r in scored:
            print(f"        {r['img_type']!s:30} {r['width_px']}x{r['height_px']}  {r['visual_interest_score']}  {r['file_name']}")
    await close_pool()
    print(f"{failures} failure(s)")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
