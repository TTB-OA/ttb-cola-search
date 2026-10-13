"""One-off: remaining backlog per enrichment component (2% sample, scaled).

Run from inside pipeline/: uv run python ../scripts/_diag_backlogs.py
"""
from cola.core.pcr_env import get_conn

S = '"pcr-prod"'

conn = get_conn()
try:
    with conn.cursor() as cur:
        cur.execute(f"""--sql
            SELECT CASE WHEN completed_date >= '2021-01-01' THEN '2021+'
                        WHEN completed_date >= '2010-01-01' THEN '2010-2020'
                        WHEN completed_date >= '2000-01-01' THEN '2000-2009'
                        ELSE 'pre-2000' END AS era,
                   50 * count(*) AS colas,
                   50 * count(*) FILTER (WHERE detail_scraped_on IS NULL) AS no_api_detail,
                   50 * count(*) FILTER (WHERE detail_scraped_on IS NULL AND received_code = 'ES') AS es_no_api_detail
              FROM {S}.colas TABLESAMPLE SYSTEM (2)
             GROUP BY 1 ORDER BY 1
        """)
        print("API detail backlog (detail_fill):")
        for row in cur.fetchall():
            print("  ", row)

        cur.execute(f"""--sql
            SELECT CASE WHEN c.completed_date >= '2021-01-01' THEN '2021+'
                        WHEN c.completed_date >= '2010-01-01' THEN '2010-2020'
                        WHEN c.completed_date >= '2000-01-01' THEN '2000-2009'
                        ELSE 'pre-2000' END AS era,
                   50 * count(*) AS label_images,
                   50 * count(*) FILTER (WHERE NOT EXISTS (
                       SELECT 1 FROM {S}.cola_image_analysis a
                        WHERE a.cola_id = i.cola_id AND a.file_name = i.file_name)) AS no_ocr,
                   50 * count(*) FILTER (WHERE i.image_feature_vector IS NULL) AS no_vector
              FROM {S}.cola_images i TABLESAMPLE SYSTEM (2)
              JOIN {S}.colas c USING (cola_id)
             WHERE i.image_role = 'label' AND i.blob_name IS NOT NULL
             GROUP BY 1 ORDER BY 1
        """)
        print("\nlabel-image backlog (OCR / embedding):")
        for row in cur.fetchall():
            print("  ", row)
finally:
    conn.close()
