"""One-off, read-only: why is the image_embedding backfill slowing down?"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from dotenv import load_dotenv

load_dotenv()
from api.db import close_pool, fetch_all, open_pool  # noqa: E402

T = 120_000

QUERIES = {
    "embedding ledger by year/status": """--sql
        SELECT extract(year FROM business_date)::int AS yr, status,
               count(*) AS days, sum(api_count) AS expected, sum(db_count) AS covered
        FROM pipeline_day_status
        WHERE component = 'image_embedding'
        GROUP BY 1, 2 ORDER BY 1 DESC, 2
    """,
    "batch jobs by state": """--sql
        SELECT state, count(*) AS jobs, sum(request_count) AS requests,
               min(submitted_on) AS oldest, max(submitted_on) AS newest,
               min(business_date) AS min_day, max(business_date) AS max_day
        FROM embedding_batch_job
        WHERE component = 'image_embedding'
        GROUP BY state ORDER BY state
    """,
    "open jobs by business year": """--sql
        SELECT extract(year FROM business_date)::int AS yr, state,
               count(*) AS jobs, sum(request_count) AS requests,
               min(submitted_on) AS oldest_submit
        FROM embedding_batch_job
        WHERE component = 'image_embedding'
          AND state IN ('submitted', 'running', 'succeeded')
        GROUP BY 1, 2 ORDER BY 1 DESC, 2
    """,
    "per-run: submitted vs collected (last 4 days)": """--sql
        WITH sub AS (
            SELECT run_name, date_trunc('hour', submitted_on) AS hr,
                   count(*) AS jobs_submitted, sum(request_count) AS req_submitted,
                   min(business_date) AS min_day, max(business_date) AS max_day
            FROM embedding_batch_job
            WHERE component = 'image_embedding'
              AND submitted_on > now() - interval '4 days'
            GROUP BY 1, 2
        ), col AS (
            SELECT date_trunc('hour', collected_on) AS hr,
                   count(*) AS jobs_collected, sum(succeeded_count) AS vec_collected
            FROM embedding_batch_job
            WHERE component = 'image_embedding'
              AND collected_on > now() - interval '4 days'
            GROUP BY 1
        )
        SELECT coalesce(s.hr, c.hr) AS hr, s.run_name, s.jobs_submitted, s.req_submitted,
               s.min_day, s.max_day, c.jobs_collected, c.vec_collected
        FROM sub s FULL JOIN col c ON c.hr = s.hr
        ORDER BY 1
    """,
    "batch vectors written per day (api_usage, last 14d)": """--sql
        SELECT recorded_on::date AS d, run_name, count(*) AS vectors,
               min(recorded_on)::time AS first, max(recorded_on)::time AS last
        FROM api_usage
        WHERE component = 'image_embedding'
          AND operation IN ('image_embedding_batch', 'text_embedding_batch')
          AND recorded_on > now() - interval '14 days'
        GROUP BY 1, 2 ORDER BY 1, 2
    """,
    "succeeded-but-uncollected age": """--sql
        SELECT count(*) AS jobs, sum(request_count) AS requests,
               min(completed_on) AS oldest_done, max(completed_on) AS newest_done,
               round(extract(epoch FROM now() - min(completed_on)) / 3600, 1) AS oldest_age_h
        FROM embedding_batch_job
        WHERE component = 'image_embedding' AND state = 'succeeded'
    """,
    "terminal-failure jobs, last 7d": """--sql
        SELECT state, left(coalesce(last_error, ''), 120) AS err, count(*) AS jobs,
               sum(request_count) AS requests
        FROM embedding_batch_job
        WHERE component = 'image_embedding'
          AND state IN ('failed', 'expired', 'cancelled')
          AND submitted_on > now() - interval '7 days'
        GROUP BY 1, 2 ORDER BY jobs DESC LIMIT 15
    """,
    "newest 25 not-complete embedding days": """--sql
        SELECT e.business_date, e.status, e.api_count, e.db_count, e.attempt_count,
               e.last_run_on, left(coalesce(e.last_error, ''), 60) AS err,
               (SELECT count(*) FROM embedding_batch_job j
                 WHERE j.component = 'image_embedding' AND j.business_date = e.business_date) AS jobs_ever,
               (SELECT count(*) FROM embedding_batch_job j
                 WHERE j.component = 'image_embedding' AND j.business_date = e.business_date
                   AND j.state IN ('submitted', 'running', 'succeeded')) AS jobs_open
        FROM pipeline_day_status e
        WHERE e.component = 'image_embedding' AND e.status <> 'complete'
        ORDER BY e.business_date DESC LIMIT 25
    """,
    "upstream (scan_extract) complete vs embedding, by year": """--sql
        SELECT extract(year FROM up.business_date)::int AS yr,
               count(*) AS upstream_complete,
               count(*) FILTER (WHERE d.status = 'complete') AS emb_complete,
               count(*) FILTER (WHERE d.status IS DISTINCT FROM 'complete') AS emb_todo
        FROM pipeline_day_status up
        LEFT JOIN pipeline_day_status d
               ON d.component = 'image_embedding' AND d.business_date = up.business_date
        WHERE up.component = 'scan_extract' AND up.status = 'complete'
        GROUP BY 1 ORDER BY 1 DESC
    """,
    "most-resubmitted days (jobs per day, last 7d)": """--sql
        SELECT business_date, count(*) AS jobs, sum(request_count) AS requests,
               count(*) FILTER (WHERE request_count < 20) AS tiny_jobs
        FROM embedding_batch_job
        WHERE component = 'image_embedding' AND submitted_on > now() - interval '7 days'
        GROUP BY 1 ORDER BY jobs DESC LIMIT 15
    """,
    "failed item errors (last 7d)": """--sql
        SELECT bi.modality, left(coalesce(bi.last_error, ''), 100) AS err, count(*) AS items
        FROM embedding_batch_item bi
        JOIN embedding_batch_job bj ON bj.job_id = bi.job_id
        WHERE bi.state = 'failed' AND bj.submitted_on > now() - interval '7 days'
        GROUP BY 1, 2 ORDER BY items DESC LIMIT 10
    """,
    "cola_images indexes and sizes": """--sql
        SELECT c.relname, pg_size_pretty(pg_relation_size(c.oid)) AS size,
               split_part(pg_get_indexdef(c.oid), ' USING ', 2) AS def
        FROM pg_index x JOIN pg_class c ON c.oid = x.indexrelid
        JOIN pg_class t ON t.oid = x.indrelid
        WHERE t.relname = 'cola_images' AND t.relnamespace = current_schema()::regnamespace
        ORDER BY pg_relation_size(c.oid) DESC
    """,
    "cola_images table/vector totals": """--sql
        SELECT pg_size_pretty(pg_total_relation_size('cola_images')) AS total,
               pg_size_pretty(pg_relation_size('cola_images')) AS heap,
               (SELECT reltuples::bigint FROM pg_class
                 WHERE oid = 'cola_images'::regclass) AS est_rows,
               current_setting('shared_buffers') AS shared_buffers,
               current_setting('maintenance_work_mem') AS mwm,
               current_setting('effective_cache_size') AS ecs
    """,
    "cola_images dead tuples / vacuum": """--sql
        SELECT n_live_tup, n_dead_tup, n_tup_upd, n_tup_hot_upd,
               last_vacuum, last_autovacuum, last_analyze, last_autoanalyze
        FROM pg_stat_user_tables
        WHERE relid = 'cola_images'::regclass
    """,
}


FOLLOWUP = {
    "batch turnaround by submit day (hours)": """--sql
        SELECT submitted_on::date AS d, count(*) AS jobs, sum(request_count) AS req,
               round(percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM completed_on - submitted_on)) / 3600, 1) AS p50_h,
               round(percentile_cont(0.9) WITHIN GROUP (ORDER BY extract(epoch FROM completed_on - submitted_on)) / 3600, 1) AS p90_h,
               round(percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM collected_on - completed_on)) / 3600, 1) AS wait_to_collect_p50_h
        FROM embedding_batch_job
        WHERE component = 'image_embedding' AND state = 'collected'
          AND submitted_on > now() - interval '14 days' AND request_count >= 100
        GROUP BY 1 ORDER BY 1
    """,
    "submit failures by day and kind": """--sql
        SELECT submitted_on::date AS d,
               count(*) FILTER (WHERE last_error ILIKE '%%spending%%') AS spend_cap,
               count(*) FILTER (WHERE last_error ILIKE '%%current quota%%') AS quota,
               sum(request_count) FILTER (WHERE last_error ILIKE '%%429%%') AS req_lost,
               pg_size_pretty(sum(request_bytes) FILTER (WHERE last_error ILIKE '%%429%%')) AS bytes_uploaded_for_nothing
        FROM embedding_batch_job
        WHERE component = 'image_embedding' AND state = 'failed'
          AND submitted_on > now() - interval '14 days'
        GROUP BY 1 ORDER BY 1
    """,
    "in-flight load at the moment of each quota 429 (last 3d)": """--sql
        SELECT f.submitted_on, f.request_count,
               (SELECT count(*) FROM embedding_batch_job o
                 WHERE o.component = 'image_embedding'
                   AND o.submitted_on < f.submitted_on
                   AND coalesce(o.completed_on, 'infinity') > f.submitted_on
                   AND o.state <> 'failed') AS jobs_in_flight,
               (SELECT sum(o.request_count) FROM embedding_batch_job o
                 WHERE o.component = 'image_embedding'
                   AND o.submitted_on < f.submitted_on
                   AND coalesce(o.completed_on, 'infinity') > f.submitted_on
                   AND o.state <> 'failed') AS requests_in_flight
        FROM embedding_batch_job f
        WHERE f.component = 'image_embedding' AND f.state = 'failed'
          AND f.last_error ILIKE '%%current quota%%'
          AND f.submitted_on > now() - interval '3 days'
        ORDER BY f.submitted_on DESC LIMIT 12
    """,
    "resubmitted 'complete' day: what the image looks like": """--sql
        SELECT i.cola_id, i.file_name, i.image_role, i.image_feature_vector IS NOT NULL AS has_vec,
               i.image_feature_vector_model AS vec_model, e.status AS emb_status,
               s.status AS scan_status, s.last_run_on AS scan_last_run, e.last_run_on AS emb_last_run
        FROM cola_images i
        JOIN colas c ON c.cola_id = i.cola_id
        LEFT JOIN pipeline_day_status e ON e.component = 'image_embedding' AND e.business_date = c.completed_date
        LEFT JOIN pipeline_day_status s ON s.component = 'scan_extract' AND s.business_date = c.completed_date
        WHERE c.completed_date IN ('2014-02-21', '2022-03-24', '2019-06-15')
          AND i.download_status = 'SUCCESS' AND i.blob_name IS NOT NULL
          AND i.image_role <> 'form_scan'
          AND (i.image_feature_vector IS NULL OR i.image_feature_vector_model IS DISTINCT FROM 'gemini-embedding-2')
    """,
    "vector model mix": """--sql
        SELECT image_feature_vector_model, count(*) FROM cola_images
        WHERE image_feature_vector IS NOT NULL GROUP BY 1
    """,
    "scan_extract ledger: not-complete by status": """--sql
        SELECT status, count(*) AS days, min(business_date), max(business_date),
               max(last_run_on) AS latest_run
        FROM pipeline_day_status WHERE component = 'scan_extract'
        GROUP BY 1
    """,
    "per embedding day retried in the last cycle (candidate churn)": """--sql
        SELECT status, count(*) AS days
        FROM pipeline_day_status
        WHERE component = 'image_embedding'
          AND last_run_on > now() - interval '2 hours'
        GROUP BY 1
    """,
    "still-invalid images (never embedded after re-encode)": """--sql
        SELECT count(DISTINCT (bi.cola_id, bi.file_name)) AS images,
               count(*) AS failed_attempts
        FROM embedding_batch_item bi
        JOIN cola_images i ON i.cola_id = bi.cola_id AND i.file_name = bi.file_name
        WHERE bi.state = 'failed' AND bi.modality = 'image'
          AND i.image_feature_vector IS NULL
    """,
}


async def main() -> None:
    queries = FOLLOWUP if "--followup" in sys.argv else QUERIES
    await open_pool()
    try:
        for title, sql in queries.items():
            print(f"\n== {title} ==")
            try:
                rows = await fetch_all(sql, statement_timeout_ms=T)
            except Exception as exc:  # noqa: BLE001
                print(f"  ERROR: {exc}")
                continue
            if not rows:
                print("  (none)")
                continue
            cols = list(rows[0].keys())
            print("  " + " | ".join(cols))
            for r in rows:
                print("  " + " | ".join(str(r[c]) for c in cols))
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
