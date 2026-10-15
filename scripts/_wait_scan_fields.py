"""Collect scan_fields_batch jobs every 60 s until none are open (pilot watcher).

Run from inside pipeline/: uv run python ../scripts/_wait_scan_fields.py
"""
import time
from collections import Counter

from cola.core.pcr_env import get_conn
from cola.pipeline.scan_fields_batch import GeminiBatchReader, collect, select_open_jobs
from cola.pipeline.scan_extract import default_scan_model


class Args:
    pass


conn = get_conn()
reader = GeminiBatchReader(default_scan_model())
total = Counter()
while True:
    stats = Counter()
    collect(conn, reader, "pcr-prod", Args(), stats)
    total.update(stats)
    print(time.strftime("%H:%M:%S"), dict(stats), flush=True)
    if not select_open_jobs(conn, "pcr-prod"):
        break
    time.sleep(60)
print("TOTAL", dict(total))
conn.close()
