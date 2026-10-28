"""Run the OCR backfill locally until the backlog is done, waiting out the cron's lock.

Launched detached (Win32_Process.Create) with the pipeline venv's python, cwd pipeline/.
Create pipeline/rpt/ocr_backfill.stop to keep it from relaunching after the current run.
Usage: python ../scripts/_ocr_backfill_loop.py
"""
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

LOCK_BUSY = 75
MAX_FAILURES = 5
STOP_FILE = Path("rpt") / "ocr_backfill.stop"
ARGS = [
    "--schema", "pcr-prod", "--mode", "backward",
    "--max-records", "1200000", "--max-images", "3000",
    "--batch-size", "60", "--batch-workers", "8",
    "--run-name", "local_ocr_backfill",
]


def log(message):
    print(f"{datetime.now(UTC):%Y-%m-%d %H:%M:%SZ} {message}", flush=True)


env = {**os.environ, "PYTHONUNBUFFERED": "1", "PCR_PROGRESS": "0"}
failures = 0

while not STOP_FILE.exists():
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = Path("rpt") / f"local_ocr_backfill_{stamp}.out.log"
    with out.open("w", encoding="utf-8") as handle:
        code = subprocess.run(
            [sys.executable, "-m", "cola.pipeline.image_analysis", *ARGS],
            stdout=handle, stderr=subprocess.STDOUT, env=env,
        ).returncode

    if code == LOCK_BUSY:
        out.unlink(missing_ok=True)
        time.sleep(15)
        continue

    log(f"run exit={code} -> {out}")
    if code == 0:
        break
    failures += 1
    if failures >= MAX_FAILURES:
        log("giving up after repeated failures")
        break
    time.sleep(60)

log("loop finished")
