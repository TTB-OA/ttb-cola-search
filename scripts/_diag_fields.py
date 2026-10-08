"""One-off: fill rates for the form fields under review (sampled)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

load_dotenv()
from api.db import close_pool, fetch_all, open_pool  # noqa: E402


async def main() -> None:
    await open_pool()
    print("== colas columns ==")
    cols = await fetch_all(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'colas' ORDER BY ordinal_position"
    )
    print("  " + ", ".join(f"{r['column_name']}:{r['data_type']}" for r in cols))

    print("\n== colas fill rates (TABLESAMPLE SYSTEM 1) by received_code ==")
    for r in await fetch_all(
        """--sql
        SELECT received_code,
               count(*) AS n,
               round(100.0 * count(detail_scraped_on) / count(*), 1) AS detail_pct,
               round(100.0 * count(formula_num) / count(*), 1) AS formula_pct,
               round(100.0 * count(application_date) / count(*), 1) AS appl_date_pct,
               round(100.0 * count(issued_date) / count(*), 1) AS issued_pct,
               round(100.0 * count(expiration_date) / count(*), 1) AS expir_pct,
               round(100.0 * count(source_of_product) / count(*), 1) AS src_pct,
               round(100.0 * count(application_type) / count(*), 1) AS appl_type_pct
          FROM colas TABLESAMPLE SYSTEM (1)
         GROUP BY received_code ORDER BY n DESC
        """
    ):
        print(f"  {dict(r)}")

    print("\n== expiration_date by status (sample) ==")
    for r in await fetch_all(
        """--sql
        SELECT status, count(*) AS n, count(expiration_date) AS with_exp
          FROM colas TABLESAMPLE SYSTEM (1)
         GROUP BY status ORDER BY n DESC
        """
    ):
        print(f"  {dict(r)}")

    print("\n== cola_submitters fill (sample) ==")
    for r in await fetch_all(
        """--sql
        SELECT count(*) AS n,
               count(tel_no) AS tel, count(fax_no) AS fax,
               count(submtr_frst_name) AS first_nm, count(submtr_last_name) AS last_nm
          FROM cola_submitters TABLESAMPLE SYSTEM (2)
        """
    ):
        print(f"  {dict(r)}")

    print("\n== formula_num samples ==")
    for r in await fetch_all(
        "SELECT formula_num, count(*) AS n FROM colas TABLESAMPLE SYSTEM (1) "
        "WHERE formula_num IS NOT NULL GROUP BY 1 ORDER BY n DESC LIMIT 12"
    ):
        print(f"  {dict(r)}")

    print("\n== sample paper (MAIL) ids, spirits then wine, post-2008 ==")
    for pattern in ("^[0-7]", "^8"):
        for r in await fetch_all(
            """--sql
            SELECT cola_id, class_type_code, completed_date
              FROM colas TABLESAMPLE SYSTEM (0.5)
             WHERE received_code = 'MAIL' AND completed_date >= '2008-01-01'
               AND class_type_code ~ %s
             LIMIT 4
            """,
            [pattern],
        ):
            print(f"  {dict(r)}")
    await close_pool()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
