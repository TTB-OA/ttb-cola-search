"""One-off: confirm superseded form scans drop out of detail/form image reads."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

load_dotenv()
from api.db import close_pool, fetch_all, open_pool  # noqa: E402
from api.routers.colas import load_detail  # noqa: E402
from api.routers.forms import _label_images  # noqa: E402


async def main() -> None:
    await open_pool()
    picks = await fetch_all(
        """--sql
        WITH sheets AS (
            SELECT s.cola_id, s.file_name,
                   (SELECT count(*) FROM cola_images c
                     WHERE c.cola_id = s.cola_id AND c.source_file_name = s.file_name) AS crops
              FROM cola_images s
             WHERE s.image_role = 'form_scan'
             ORDER BY s.cola_id DESC
             LIMIT 2000
        )
        (SELECT * FROM sheets WHERE crops > 0 LIMIT 1)
        UNION ALL
        (SELECT s.cola_id, s.file_name, 0::bigint FROM cola_images s
          WHERE s.image_role = 'form_scan'
            AND NOT EXISTS (SELECT 1 FROM cola_images c
                             WHERE c.cola_id = s.cola_id AND c.source_file_name = s.file_name)
          LIMIT 1)
        """
    )
    with_crops = next((p for p in picks if p["crops"]), None)
    without = next((p for p in picks if not p["crops"]), None)
    for label, pick in (("with crops", with_crops), ("no crops", without)):
        if pick is None:
            print(label, "-> none in sample")
            continue
        d = await load_detail(pick["cola_id"])
        forms = await _label_images(pick["cola_id"])
        print(label, pick["cola_id"], "sheet", pick["file_name"], "crops", pick["crops"])
        print("  detail images:", [i.file_name for i in d.images])
        print("  detail item files:", sorted({i.file for i in d.image_items}))
        print("  form images:", [i.file_name for i in forms])
    await close_pool()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
