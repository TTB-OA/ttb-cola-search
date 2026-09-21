"""One-off: inspect the post-migration search surface."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

load_dotenv()
from api.db import close_pool, fetch_all, open_pool  # noqa: E402


async def main() -> None:
    await open_pool()
    print("== indexes on cola_search / cola_search_detail / cola_images ==")
    for r in await fetch_all(
        "SELECT tablename, indexname, pg_get_indexdef(indexrelid) AS def, x.indisvalid "
        "FROM pg_indexes i JOIN pg_class c ON c.relname = i.indexname "
        "JOIN pg_index x ON x.indexrelid = c.oid "
        "WHERE schemaname = current_schema() AND tablename IN ('cola_search','cola_search_detail','cola_images') "
        "ORDER BY tablename, indexname"
    ):
        print(f"{r['tablename']:20} {r['indexname']:48} valid={r['indisvalid']}  {r['def'].split(' USING ',1)[1]}")
    print("\n== cola_search_detail columns ==")
    for r in await fetch_all(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'cola_search_detail' ORDER BY ordinal_position"
    ):
        print(f"  {r['column_name']}: {r['data_type']}")
    print("\n== weighted tsquery rewrite ==")
    for q in ['vodka', 'cabernet sauvignon', '"napa valley" -reserve', 'vodka or gin', 'the', "o'brien"]:
        r = await fetch_all(
            "SELECT websearch_to_tsquery('english', %s)::text AS plain, "
            "regexp_replace(websearch_to_tsquery('english', %s)::text, "
            "'''((?:[^'']|'''')*)''', '''\\1'':ABC', 'g')::tsquery::text AS abc, "
            "regexp_replace(websearch_to_tsquery('english', %s)::text, "
            "'''((?:[^'']|'''')*)''', '''\\1'':D', 'g')::tsquery::text AS d",
            [q, q, q],
        )
        print(f"  {q!r:28} plain={r[0]['plain']!r:40} abc={r[0]['abc']!r:48} d={r[0]['d']!r}")
    print("\n== sanity: weight-restricted match counts on a sample ==")
    r = await fetch_all(
        "SELECT count(*) FILTER (WHERE search_tsv @@ to_tsquery('english','vodka')) AS any_w, "
        "count(*) FILTER (WHERE search_tsv @@ to_tsquery('english','vodka:ABC')) AS abc, "
        "count(*) FILTER (WHERE search_tsv @@ to_tsquery('english','vodka:D')) AS d, "
        "count(*) FILTER (WHERE search_tsv @@ to_tsquery('english','vodka:D') AND NOT search_tsv @@ to_tsquery('english','vodka:ABC')) AS d_only "
        "FROM cola_search TABLESAMPLE SYSTEM (2)"
    )
    print(f"  {r[0]}")
    print("\n== ts_filter form agrees with the weighted-tsquery form (sample) ==")
    for q in ["vodka", "cabernet sauvignon", '"napa valley"', "organic"]:
        r = await fetch_all(
            """--sql
            SELECT count(*) FILTER (WHERE search_tsv @@ regexp_replace(websearch_to_tsquery('english', %s)::text,
                       '''((?:[^'']|'''')*)''', '''\\1'':ABC', 'g')::tsquery) AS abc_weighted,
                   count(*) FILTER (WHERE ts_filter(search_tsv, '{a,b,c}'::"char"[]) @@ websearch_to_tsquery('english', %s)) AS abc_filter,
                   count(*) FILTER (WHERE search_tsv @@ regexp_replace(websearch_to_tsquery('english', %s)::text,
                       '''((?:[^'']|'''')*)''', '''\\1'':D', 'g')::tsquery) AS d_weighted,
                   count(*) FILTER (WHERE ts_filter(search_tsv, '{d}'::"char"[]) @@ websearch_to_tsquery('english', %s)) AS d_filter
              FROM cola_search TABLESAMPLE SYSTEM (1)
            """,
            [q, q, q, q],
        )
        print(f"  {q!r:22} {r[0]}")
    print("\n== full match vs (record OR label) match: rows only the full form finds (sample) ==")
    for q in ["vodka", "cabernet sauvignon", "estate bottled reserve", '"napa valley"', "organic wine", "vodka or gin"]:
        r = await fetch_all(
            """--sql
            SELECT count(*) FILTER (WHERE search_tsv @@ websearch_to_tsquery('english', %s)) AS full,
                   count(*) FILTER (WHERE ts_filter(search_tsv, '{a,b,c}'::"char"[]) @@ websearch_to_tsquery('english', %s)
                                     OR ts_filter(search_tsv, '{d}'::"char"[]) @@ websearch_to_tsquery('english', %s)) AS split_or,
                   count(*) FILTER (WHERE search_tsv @@ websearch_to_tsquery('english', %s)
                                     AND NOT (ts_filter(search_tsv, '{a,b,c}'::"char"[]) @@ websearch_to_tsquery('english', %s)
                                           OR ts_filter(search_tsv, '{d}'::"char"[]) @@ websearch_to_tsquery('english', %s))) AS full_only
              FROM cola_search TABLESAMPLE SYSTEM (2)
            """,
            [q] * 6,
        )
        print(f"  {q!r:26} {r[0]}")
    print("\n== ref_received_codes ==")
    for r in await fetch_all("SELECT * FROM ref_received_codes LIMIT 10"):
        print(f"  {r}")
    await close_pool()


asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
