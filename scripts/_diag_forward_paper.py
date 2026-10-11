"""One-off: paper COLAs touched by the scheduled legs since the form-field deploy."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

load_dotenv()
from api.db import close_pool, fetch_all, open_pool  # noqa: E402

DEPLOYED = os.environ.get("DIAG_DEPLOYED", "2026-10-09 00:00+00")


async def main() -> None:
    await open_pool()
    print(f"paper COLAs whose image rows were first written after {DEPLOYED} (backward image leg)")
    for r in await fetch_all(
        """--sql
        WITH fresh AS (
            SELECT i.cola_id
              FROM cola_images i
             WHERE i.scraped_on >= %s::timestamptz
             GROUP BY i.cola_id
            HAVING min(i.scraped_on) >= %s::timestamptz
        )
        SELECT c.received_code, count(*) AS n,
               count(c.form_scraped_on) AS form_read,
               count(*) FILTER (WHERE c.form_view = 'search') AS search_view,
               count(*) FILTER (WHERE c.form_view = 'form') AS form_view,
               count(c.formula_num) AS formula, count(c.wine_vintage) AS vintage,
               count(c.applicant_phone) AS phone, count(c.application_type) AS appl_type
          FROM fresh f JOIN colas c USING (cola_id)
         WHERE c.received_code <> 'ES'
         GROUP BY 1 ORDER BY n DESC
        """,
        [DEPLOYED, DEPLOYED],
    ):
        print("  " + "  ".join(f"{k}={v}" for k, v in dict(r).items()))

    print(f"\nscan_extract reads completed after {DEPLOYED} (backward scan leg)")
    r = (await fetch_all(
        """--sql
        SELECT count(*) AS scans,
               count(*) FILTER (WHERE x.metadata -> 'form_flags' ? 'printed_name') AS new_schema,
               count(*) FILTER (WHERE x.metadata -> 'form_flags' ->> 'printed_name' IS NOT NULL) AS read_printed_name,
               count(*) FILTER (WHERE x.metadata -> 'form_flags' ->> 'formula_num' IS NOT NULL) AS read_formula,
               count(*) FILTER (WHERE x.metadata -> 'form_flags' ->> 'applicant_phone' IS NOT NULL) AS read_phone,
               count(*) FILTER (WHERE x.metadata -> 'form_flags' ->> 'appellation' IS NOT NULL) AS read_appellation,
               count(*) FILTER (WHERE x.metadata -> 'form_flags' ->> 'applicant_signature' IS NOT NULL) AS read_signed,
               count(*) FILTER (WHERE (x.metadata -> 'form_flags' ->> 'ttb_signed')::boolean) AS read_ttb_signed,
               min(x.completed_on) AS first, max(x.completed_on) AS last
          FROM cola_scan_extraction x
         WHERE x.completed_on >= %s::timestamptz
        """,
        [DEPLOYED],
    ))[0]
    print("  " + "  ".join(f"{k}={v}" for k, v in dict(r).items()))

    print("\n  those scanned COLAs in colas now:")
    r = (await fetch_all(
        """--sql
        SELECT count(DISTINCT c.cola_id) AS colas,
               count(DISTINCT c.cola_id) FILTER (WHERE c.printed_name IS NOT NULL) AS printed_name,
               count(DISTINCT c.cola_id) FILTER (WHERE c.formula_num IS NOT NULL) AS formula,
               count(DISTINCT c.cola_id) FILTER (WHERE c.applicant_phone IS NOT NULL) AS phone,
               count(DISTINCT c.cola_id) FILTER (WHERE c.application_date IS NOT NULL) AS appl_date
          FROM cola_scan_extraction x JOIN colas c USING (cola_id)
         WHERE x.completed_on >= %s::timestamptz
        """,
        [DEPLOYED],
    ))[0]
    print("  " + "  ".join(f"{k}={v}" for k, v in dict(r).items()))
    await close_pool()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
