"""Wait for running backfill PIDs to exit, then run a sequence of form-field backfills.

Launched detached (Win32_Process.Create) with the pipeline venv's python, cwd pipeline/.
Usage: python ../scripts/_chain_backfills.py PID [PID ...]
"""
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

PIDS = [int(p) for p in sys.argv[1:]]
COMMON = ["--backfill-form-flags", "--imaged-only", "--schema", "pcr-prod"]
STEPS = [
    ("retry_2010_2014", ["--start-date", "2010-01-01", "--end-date", "2014-12-31"]),
    ("form_backfill_2003_2009_efiled",
     ["--efiled-only", "--start-date", "2003-01-01", "--end-date", "2009-12-31"]),
]


def alive(pid):
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                         capture_output=True, text=True).stdout
    return str(pid) in out


def log(message):
    print(f"{datetime.now(UTC):%Y-%m-%d %H:%M:%SZ} {message}", flush=True)


while any(alive(pid) for pid in PIDS):
    time.sleep(60)
log(f"pids {PIDS} exited")

for stem, args in STEPS:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = Path("rpt") / f"{stem}_{stamp}.out.log"
    log(f"start {stem} -> {out}")
    with out.open("w", encoding="utf-8") as handle:
        code = subprocess.run(
            [sys.executable, "-m", "cola.pipeline.image_ingest", *COMMON, *args],
            stdout=handle, stderr=subprocess.STDOUT,
        ).returncode
    log(f"done {stem} exit={code}")
