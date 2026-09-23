"""Temporary diagnostic: search-surface size, index usage, pg_stat_statements,
and EXPLAIN ANALYZE of the exact SQL each search endpoint issues."""
import asyncio
import os
import sys
import time
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv

load_dotenv()

from api.db import close_pool, fetch_all, open_pool, transaction_cursor  # noqa: E402
from api.mappers import (  # noqa: E402
    OCR_TABLE,
    PERMIT_TABLE,
    SEARCH_TABLE,
    SUMMARY_COLUMN_LIST,
    select_columns,
)
from api.routers.colas import (  # noqa: E402
    COUNT_CAP,
    _and,
    _build_filters,
    _keyword_source,
    _order_by,
    _term_params,
    compose,
    filtered_source,
    only_status_filtered,
    record_match,
)

TABLES = ["cola_search", "cola_search_ocr", "cola_images", "cola_permit_search",
          "cola_map_search", "cola_search_dirty", "cola_map_dirty"]

ONLY = set(os.environ.get("DIAG_ONLY", "").split(",")) - {""}


def hr(title: str) -> None:
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)


def table(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("(no rows)")
        return
    cols = list(rows[0].keys())
    widths = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    print(" | ".join(c.ljust(widths[c]) for c in cols))
    print("-+-".join("-" * widths[c] for c in cols))
    for r in rows:
        print(" | ".join(str(r[c]).ljust(widths[c]) for c in cols))


async def sizes() -> None:
    hr("TABLE SIZES / ROW ESTIMATES")
    table(await fetch_all(
        """--sql
        SELECT c.relname AS table,
               to_char(c.reltuples, 'FM999,999,999,999') AS est_rows,
               pg_size_pretty(pg_table_size(c.oid)) AS heap_toast,
               pg_size_pretty(pg_indexes_size(c.oid)) AS indexes,
               pg_size_pretty(pg_total_relation_size(c.oid)) AS total,
               s.n_dead_tup, s.last_autovacuum::timestamp(0), s.last_autoanalyze::timestamp(0)
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
          LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
         WHERE n.nspname = current_schema() AND c.relname = ANY(%s) AND c.relkind IN ('r','m','p')
         ORDER BY pg_total_relation_size(c.oid) DESC
        """, [TABLES]))
    hr("MAIN FORK vs TOAST (what a heap fetch of a narrow column set actually touches)")
    table(await fetch_all(
        """--sql
        SELECT c.relname AS table,
               pg_size_pretty(pg_relation_size(c.oid, 'main')) AS main_heap,
               pg_size_pretty(coalesce(pg_relation_size(c.reltoastrelid, 'main'), 0)) AS toast,
               pg_size_pretty(pg_relation_size(c.oid, 'vm')) AS visibility_map,
               round(pg_relation_size(c.oid, 'main') / GREATEST(c.reltuples, 1)) AS main_bytes_per_row,
               c.reloptions
          FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = current_schema() AND c.relname = ANY(%s) AND c.relkind = 'r'
         ORDER BY pg_relation_size(c.oid, 'main') DESC
        """, [TABLES]))
    table(await fetch_all(
        """--sql
        SELECT table_name, string_agg(column_name || ':' || data_type, ', ' ORDER BY ordinal_position) AS cols
          FROM information_schema.columns
         WHERE table_schema = current_schema() AND table_name IN ('cola_search_ocr')
         GROUP BY 1
        """))
    table(await fetch_all(
        "SELECT status, count(*) FROM (SELECT status FROM cola_search TABLESAMPLE SYSTEM (1)) s GROUP BY 1 ORDER BY 2 DESC"))
    hr("SERVER")
    table(await fetch_all(
        """--sql
        SELECT name, setting, unit FROM pg_settings
         WHERE name IN ('server_version','shared_buffers','work_mem','effective_cache_size',
                        'random_page_cost','max_parallel_workers_per_gather','jit',
                        'shared_preload_libraries','pg_stat_statements.track','track_io_timing')
        """))
    table(await fetch_all(
        "SELECT extname, extversion FROM pg_extension ORDER BY 1"))


async def indexes() -> None:
    hr("INDEXES ON SEARCH SURFACE (with scan counts since last stats reset)")
    table(await fetch_all(
        """--sql
        SELECT i.relname AS index, t.relname AS table,
               pg_size_pretty(pg_relation_size(i.oid)) AS size,
               s.idx_scan, s.idx_tup_read, s.idx_tup_fetch,
               left(pg_get_indexdef(i.oid), 160) AS def
          FROM pg_index x
          JOIN pg_class i ON i.oid = x.indexrelid
          JOIN pg_class t ON t.oid = x.indrelid
          JOIN pg_namespace n ON n.oid = t.relnamespace
          LEFT JOIN pg_stat_user_indexes s ON s.indexrelid = i.oid
         WHERE n.nspname = current_schema() AND t.relname = ANY(%s)
         ORDER BY t.relname, s.idx_scan DESC NULLS LAST
        """, [TABLES]))
    hr("TABLE SCAN MIX (seq vs index)")
    table(await fetch_all(
        """--sql
        SELECT relname, seq_scan, seq_tup_read, idx_scan, idx_tup_fetch,
               n_tup_ins, n_tup_upd, n_tup_del, n_live_tup, n_dead_tup
          FROM pg_stat_user_tables WHERE relname = ANY(%s) ORDER BY relname
        """, [TABLES]))


async def stat_statements() -> None:
    hr("pg_stat_statements")
    ext = await fetch_all("SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements'")
    if not ext:
        print("extension not installed")
        return
    try:
        rows = await fetch_all(
            """--sql
            SELECT calls,
                   round(total_exec_time/1000)::bigint AS total_s,
                   round(mean_exec_time)::bigint AS mean_ms,
                   round(max_exec_time)::bigint AS max_ms,
                   round(stddev_exec_time)::bigint AS sd_ms,
                   rows / GREATEST(calls,1) AS rows_per_call,
                   round(100.0 * shared_blks_hit / NULLIF(shared_blks_hit + shared_blks_read, 0)) AS hit_pct,
                   (shared_blks_read + shared_blks_hit) / GREATEST(calls,1) AS blks_per_call,
                   temp_blks_written / GREATEST(calls,1) AS temp_per_call,
                   left(regexp_replace(query, '\\s+', ' ', 'g'), 220) AS query
              FROM pg_stat_statements
             WHERE query ILIKE ANY (ARRAY['%%cola_search%%','%%cola_images%%','%%cola_permit_search%%','%%cola_map_search%%'])
               AND query NOT ILIKE '%%pg_stat_statements%%'
               AND calls >= 3
             ORDER BY total_exec_time DESC
             LIMIT 30
            """)
        print("-- by total time --")
        table(rows)
        rows = await fetch_all(
            """--sql
            SELECT calls, round(mean_exec_time)::bigint AS mean_ms, round(max_exec_time)::bigint AS max_ms,
                   round(100.0 * shared_blks_hit / NULLIF(shared_blks_hit + shared_blks_read, 0)) AS hit_pct,
                   left(regexp_replace(query, '\\s+', ' ', 'g'), 220) AS query
              FROM pg_stat_statements
             WHERE query ILIKE ANY (ARRAY['%%cola_search%%','%%cola_images%%','%%cola_permit_search%%','%%cola_map_search%%'])
               AND query NOT ILIKE '%%pg_stat_statements%%'
               AND calls >= 3
             ORDER BY mean_exec_time DESC
             LIMIT 20
            """)
        print("\n-- by mean time --")
        table(rows)
        table(await fetch_all("SELECT stats_reset FROM pg_stat_statements_info"))
    except Exception as exc:  # noqa: BLE001
        print(f"could not read pg_stat_statements: {exc}")


async def explain(label: str, sql: str, params: list[Any], setup: list[str] | None = None) -> None:
    print(f"\n--- {label} ---")
    async with transaction_cursor() as cur:
        await cur.execute("SELECT set_config('statement_timeout', %s, true)", [os.environ.get("DIAG_TIMEOUT", "120s")])
        await cur.execute("SELECT set_config('work_mem', %s, true)", [os.environ.get("DIAG_WORK_MEM", "64MB")])
        for s in setup or []:
            await cur.execute(s)
        t0 = time.perf_counter()
        try:
            await cur.execute("EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT TEXT) " + sql, params)
            rows = await cur.fetchall()
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED after {time.perf_counter()-t0:.1f}s: {exc}")
            return
        plan = [list(r.values())[0] for r in rows]
    wall = time.perf_counter() - t0
    # Keep the full plan for the hot ones; they are what we are here for.
    print(f"wall {wall*1000:.0f} ms")
    for line in plan:
        print("  " + line)


def list_sql(**filters: Any) -> tuple[list[tuple[str, str, list[Any]]]]:
    """Reproduce exactly the statements /api/colas issues (rows tiers, and count+facets)."""
    args = dict(ttb_id=None, brand=None, fanciful=None, commodity=None, source=None,
                origin=None, status=None, date_from=None, date_to=None)
    q = (filters.pop("q", None) or "").strip()
    sort = filters.pop("sort", "relevance")
    page = filters.pop("page", 1)
    page_size = filters.pop("page_size", 24)
    args.update(filters)
    extra: list = []
    where, where_params = _build_filters(**args)
    all_filters = dict(args)
    ranked = bool(q) and sort == "relevance"
    offset = (page - 1) * page_size
    cols = select_columns(SUMMARY_COLUMN_LIST, SEARCH_TABLE)

    def rows_sql(sources, where_sql: str, ranked_source: bool):
        with_sql, from_sql, source_params = compose(sources)
        outer = where_params if where_sql else []
        return (f"{with_sql} SELECT {cols} FROM {from_sql} {where_sql} "
                f"ORDER BY {_order_by(sort, ranked=ranked_source)} LIMIT %s OFFSET %s",
                [*source_params, *outer, page_size + 1, offset])

    stmts: list[tuple[str, str, list[Any]]] = []
    if ranked:
        if only_status_filtered(all_filters) and offset <= 240:
            sql, params = rows_sql([], _and(where, record_match()), False)
            stmts.append(("rows tier1 (record-only predicate)", sql, [*_term_params(q), *params]))
        else:
            stmts.append(("rows tier2 (record-only source)",
                          *rows_sql([_keyword_source(q, where, where_params, record_only=True)], "", False)))
    if q:
        stmts.append(("rows tier3 (full)",
                      *rows_sql([_keyword_source(q, where, where_params, ranked=ranked)], "", ranked)))
        with_sql, from_sql, source_params = compose([_keyword_source(q, where, where_params)])
        agg_where, agg_params = "", []
    else:
        stmts.append(("rows tier3 (full)", *rows_sql([], where, False)))
        if args.get("label_text"):
            stmts.append(("rows label (filtered source)",
                          *rows_sql([filtered_source(where, where_params)], "", False)))
        with_sql, from_sql, source_params = "", SEARCH_TABLE, []
        agg_where, agg_params = where, where_params
    agg_sql = f"""--sql
        {with_sql}{', ' if with_sql else 'WITH '}m AS (
          SELECT ct_commodity, ct_source, origin, status, primary_permit_state_addr
          FROM {from_sql} {agg_where} LIMIT %s
        )
        SELECT 'total' AS dim, NULL::text AS value, COUNT(*) AS count FROM m
        UNION ALL SELECT 'commodity', ct_commodity, COUNT(*) FROM m GROUP BY 1, 2
        UNION ALL SELECT 'source', ct_source, COUNT(*) FROM m GROUP BY 1, 2
        UNION ALL SELECT 'origin', origin, COUNT(*) FROM m GROUP BY 1, 2
        UNION ALL SELECT 'status', status, COUNT(*) FROM m GROUP BY 1, 2
        UNION ALL SELECT 'permitState', primary_permit_state_addr, COUNT(*) FROM m GROUP BY 1, 2
        """
    stmts.append(("count+facets", agg_sql, [*source_params, *agg_params, COUNT_CAP + 1]))
    return (stmts,)  # type: ignore[return-value]


LIST_CASES: dict[str, dict[str, Any]] = {
    # What the SPA actually sends on the landing page (App Insights: 1185 of
    # 1800 searches in 60d are exactly this shape).
    "landing_status_approved": {"status": "Approved", "sort": "approvalDate"},
    "landing_status_approved_page3": {"status": "Approved", "sort": "approvalDate", "page": 3},
    "status_approved_sort_brand": {"status": "Approved", "sort": "brand"},
    "status_approved_sort_applicant_date": {"status": "Approved", "sort": "applicant", "date_from": "2020-01-01"},
    "status_expired": {"status": "Expired", "sort": "approvalDate"},
    "q_vodka_status": {"q": "vodka", "status": "Approved"},
    "q_vodka_status_date_sort": {"q": "vodka", "status": "Approved", "sort": "approvalDate"},
    "browse_default": {},
    "browse_page_200": {"page": 200},
    "browse_brand_sort": {"sort": "brand"},
    "q_vodka": {"q": "vodka"},
    "q_cabernet_sauvignon": {"q": "cabernet sauvignon"},
    "q_phrase_napa": {"q": '"napa valley"'},
    "q_phrase_napa_status": {"q": '"napa valley"', "status": "Approved"},
    "q_three_terms_status": {"q": "estate bottled reserve", "status": "Approved"},
    "q_rare_id": {"q": "26J087"},
    "q_vodka_wine_filter": {"q": "vodka", "commodity": "Wine"},
    "q_vodka_page_20": {"q": "vodka", "page": 20},
    "brand_ilike_stone": {"brand": "stone"},
    "fanciful_ilike_reserve": {"fanciful": "reserve"},
    "business_cedar": {"business": "cedar"},
    "permit_prefix": {"permit": "BWN-CA"},
    "q_plus_business": {"q": "reserve", "business": "cedar", "status": "Approved"},
    "received_by_desc": {"received_by": "Mailed paper submission", "status": "Approved"},
    "class_type_rare": {"class_type": "MEAD", "status": "Approved"},
    "permit_city_only": {"permit_city": "napa", "status": "Approved"},
    "varietal_pinot": {"varietal": "pinot"},
    "qualification_ilike": {"qualification": "sulfite"},
    "label_text_only": {"label_text": "organic"},
    "label_hangover_status": {"label_text": "hangover", "status": "Approved"},
    "label_organic_status": {"label_text": "organic", "status": "Approved"},
    "label_alcohol_status": {"label_text": "alcohol", "status": "Approved"},
    "label_hangover_wine": {"label_text": "hangover", "status": "Approved", "commodity": "wine"},
    "commodity_date_range": {"commodity": "Wine", "date_from": "2015-01-01", "date_to": "2015-12-31"},
    "state_only": {"permit_state": "CA"},
    "state_city": {"permit_state": "CA", "permit_city": "napa"},
    "class_type": {"class_type": "TABLE RED WINE"},
    "application_type": {"application_type": "CERTIFICATE OF LABEL APPROVAL"},
    "submitter": {"submitter": "smith"},
}


async def list_endpoint() -> None:
    hr("/api/colas — EXPLAIN ANALYZE per filter shape (count / rows / facets)")
    from datetime import date
    for name, f in LIST_CASES.items():
        if ONLY and name not in ONLY:
            continue
        f = {k: (date.fromisoformat(v) if k in ("date_from", "date_to") else v) for k, v in f.items()}
        print(f"\n######## {name}: {f}")
        (stmts,) = list_sql(**f)
        for label, sql, params in stmts:
            await explain(label, sql, params)


async def ann_endpoint() -> None:
    hr("/api/search/describe|image + /colas/{id}/similar — HNSW ANN")
    seed = await fetch_all(
        "SELECT ci.cola_id, ci.image_feature_vector::text AS vec, v.permit_num "
        f"FROM cola_images ci JOIN {SEARCH_TABLE} v ON v.cola_id = ci.cola_id "
        "WHERE ci.image_feature_vector IS NOT NULL AND v.permit_num IS NOT NULL "
        "ORDER BY ci.cola_id DESC LIMIT 1")
    if not seed:
        print("no vectors")
        return
    vec, cola_id, permit = seed[0]["vec"], seed[0]["cola_id"], seed[0]["permit_num"]
    print(f"seed cola {cola_id}, permit {permit}")
    # Any full aggregate over cola_search/cola_images blows the 15s statement
    # timeout at this size, so no live vector count here; the HNSW index size in
    # the sizes section is the proxy.

    setup = [
        "SET LOCAL hnsw.ef_search TO 1000",
        "SET LOCAL hnsw.iterative_scan TO relaxed_order",
        "SET LOCAL hnsw.max_scan_tuples TO 200000",
        "SET LOCAL hnsw.scan_mem_multiplier TO 4",
        "SET LOCAL work_mem TO '64MB'",
        "SET LOCAL enable_seqscan TO off",
    ]
    # Same expression the app orders by, so the same index serves it.
    from api.config import get_settings
    settings = get_settings()
    if settings.ann_halfvec:
        dim = settings.embedding_dim
        distance = f"i.image_feature_vector::halfvec({dim}) <=> %s::halfvec({dim})"
    else:
        distance = "i.image_feature_vector <=> %s::vector"
    print(f"distance: {distance}")
    base = f"""--sql
        WITH knn AS (
          SELECT i.cola_id, ({distance}) AS dist
          FROM cola_images i
          WHERE {{where}}
          ORDER BY {distance}
          LIMIT %s
        ), best AS (
          SELECT DISTINCT ON (cola_id) cola_id, dist FROM knn ORDER BY cola_id, dist
        )
        SELECT {select_columns(SUMMARY_COLUMN_LIST, 'v')}, b.dist
        FROM best b JOIN {SEARCH_TABLE} v ON v.cola_id = b.cola_id
        {{outer}} ORDER BY b.dist LIMIT %s
    """
    cases = [
        ("describe/image: global, 5000 candidates, limit 48",
         base.format(where="i.image_feature_vector IS NOT NULL", outer=""),
         [vec, vec, 5000, 48]),
        ("describe: commodity filter (outer) limit 48",
         base.format(where="i.image_feature_vector IS NOT NULL", outer="WHERE v.ct_commodity = %s"),
         [vec, vec, 5000, "wine", 48]),
        ("similar scope=all limit 12 (still 5000 candidates)",
         base.format(where="i.image_feature_vector IS NOT NULL AND i.cola_id <> %s", outer=""),
         [vec, cola_id, vec, 5000, 12]),
        ("similar scope=member",
         base.format(where="i.image_feature_vector IS NOT NULL AND i.cola_id <> %s AND "
                     f"i.cola_id IN (SELECT cola_id FROM {SEARCH_TABLE} WHERE permit_num = %s)", outer=""),
         [vec, cola_id, permit, vec, 5000, 12]),
        ("similar scope=others",
         base.format(where="i.image_feature_vector IS NOT NULL AND i.cola_id <> %s AND "
                     f"i.cola_id NOT IN (SELECT cola_id FROM {SEARCH_TABLE} WHERE permit_num = %s)", outer=""),
         [vec, cola_id, permit, vec, 5000, 12]),
        ("control: 288 candidates (old overfetch only), limit 48",
         base.format(where="i.image_feature_vector IS NOT NULL", outer=""),
         [vec, vec, 288, 48]),
    ]
    for label, sql, params in cases:
        await explain(label, sql, params, setup)

    print("\n--- similar: seed lookup ---")
    from api.mappers import image_display_order_sql, visual_interest_hero_join_sql
    await explain(
        "seed vector",
        "SELECT ci.image_feature_vector::text AS vec FROM cola_images ci "
        f"{visual_interest_hero_join_sql('ci')} "
        "WHERE ci.cola_id = %s AND ci.image_feature_vector IS NOT NULL "
        f"ORDER BY {image_display_order_sql('ci', out=None)} LIMIT 1", [cola_id])


async def suggest_endpoint() -> None:
    hr("/api/suggest/permits")
    sql = (f"SELECT permit_id, permit_name, permit_city_addr, permit_state_addr, cola_count "
           f"FROM {PERMIT_TABLE} WHERE permit_id LIKE %s OR names_blob ILIKE %s "
           "ORDER BY cola_count DESC, permit_id LIMIT %s")
    await explain("name 'cedar'", sql, ["CEDAR%", "%cedar%", 8])
    await explain("name 'the'", sql, ["THE%", "%the%", 8])
    await explain("id 'BWN-CA'", sql, ["BWN-CA%", "%BWN-CA%", 8])


async def detail_endpoint() -> None:
    hr("/api/colas/{id} detail")
    row = await fetch_all(f"SELECT cola_id FROM {SEARCH_TABLE} WHERE image_vector_count > 0 ORDER BY cola_id DESC LIMIT 1")
    if not row:
        return
    cid = row[0]["cola_id"]
    from api.mappers import DETAIL_COLUMNS, image_display_order_sql, visual_interest_join_sql
    await explain("base", f"SELECT {DETAIL_COLUMNS} FROM {SEARCH_TABLE} WHERE cola_id = %s", [cid])
    await explain("images",
        "SELECT ci.cola_id, ci.file_name, ci.img_type, ci.width_px, ci.height_px, "
        "vi.visual_interest_score, vi.visual_interest_rank FROM cola_images ci "
        f"{visual_interest_join_sql('ci')} WHERE ci.cola_id = %s ORDER BY {image_display_order_sql('ci')}", [cid])
    await explain("ocr semi-join alone",
        f"SELECT cola_id FROM {OCR_TABLE} WHERE ocr_tsv @@ websearch_to_tsquery('english', %s)", ["vodka"])


async def orlist_experiment() -> None:
    """Record-only keyword pass as a plain OR predicate (no join), so the planner
    may walk the sort index and filter instead of aggregating every match."""
    hr("EXPERIMENT: record-only pass as OR-list on cola_search")
    cols = select_columns(SUMMARY_COLUMN_LIST, SEARCH_TABLE)
    pred = ("(search_tsv @@ websearch_to_tsquery('english', %s) OR cola_id = %s "
            "OR serial_num = %s OR permit_num = %s OR primary_permit_id = %s)")
    for label, term, extra, extra_params in [
        ("vodka + status", "vodka", "AND status = %s", ["Approved"]),
        ("cabernet sauvignon + status", "cabernet sauvignon", "AND status = %s", ["Approved"]),
        ("napa valley phrase + status", '"napa valley"', "AND status = %s", ["Approved"]),
        ("rare id + status", "26J087", "AND status = %s", ["Approved"]),
        ("medium term 'hibiscus' + status", "hibiscus", "AND status = %s", ["Approved"]),
        ("vodka + commodity Wine (correlation trap)", "vodka", "AND ct_commodity = %s", ["wine"]),
        ("vodka + date 2015", "vodka", "AND completed_date >= %s AND completed_date <= %s",
         ["2015-01-01", "2015-12-31"]),
    ]:
        up = term.strip().upper()
        await explain(
            label,
            f"SELECT {cols} FROM {SEARCH_TABLE} WHERE {pred} {extra} "
            f"ORDER BY completed_date DESC NULLS LAST, {SEARCH_TABLE}.cola_id DESC LIMIT 25 OFFSET 0",
            [term, up, up, up, up, *extra_params],
        )


async def main() -> None:
    await open_pool()
    sections = {
        "sizes": sizes, "indexes": indexes, "stats": stat_statements,
        "list": list_endpoint, "ann": ann_endpoint, "suggest": suggest_endpoint, "detail": detail_endpoint,
        "orlist": orlist_experiment,
    }
    wanted = set(os.environ.get("DIAG_SECTIONS", ",".join(sections)).split(","))
    for name, fn in sections.items():
        if name in wanted:
            await fn()
    await close_pool()


asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
