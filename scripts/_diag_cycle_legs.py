"""One-off: per-leg duration and stop reason over the last N scheduled pipeline runs.

Usage: uv run python scripts/_diag_cycle_legs.py [N]
"""
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime

REPO = "TTB-OA/cola-data-scraping"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 6
PATTERNS = re.compile(
    r"(Run totals|records=|stopped|stand(s|ing)? down|budget|deadline|Backfill targets|"
    r"status=(complete|pending)|reconciled|queue|exhausted|nothing|no days|"
    r"\[DETAIL\]|\[ANALYSIS\]|\[EMBED|\[GEO|\[SCAN_EXTRACT\] \d{4}|\[MATERIALIZE|stop_reason|STOP)",
    re.IGNORECASE,
)


def gh(*args):
    return subprocess.run(["gh", *args, "-R", REPO], capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout


def ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


runs = json.loads(gh("run", "list", "--event", "schedule", "-L", str(N + 2), "--json",
                     "databaseId,status,createdAt"))
runs = [r for r in runs if r["status"] == "completed"][:N]

durations = defaultdict(list)
last_logs = {}
for run in runs:
    raw = gh("run", "view", str(run["databaseId"]), "--json", "jobs")
    if not raw.strip():
        print(f"  (skipped run {run['databaseId']}: empty gh response)")
        continue
    jobs = json.loads(raw)["jobs"]
    for job in jobs:
        start, end = ts(job.get("startedAt")), ts(job.get("completedAt"))
        if not start or not end or job.get("conclusion") == "skipped":
            continue
        name = job["name"].split(" / ")[0]
        durations[name].append(((end - start).total_seconds() / 60, job.get("conclusion")))
        if run is runs[0]:
            last_logs[name] = job["databaseId"]

print(f"last {len(runs)} scheduled runs, minutes per leg (newest first):")
for name, values in sorted(durations.items()):
    mins = ", ".join(f"{m:4.1f}" for m, _ in values)
    bad = [c for _, c in values if c != "success"]
    print(f"  {name:30} {mins}" + (f"   non-success: {bad}" if bad else ""))

print(f"\nstop lines from run {runs[0]['databaseId']} ({runs[0]['createdAt']}):")
for name, job_id in sorted(last_logs.items()):
    log = gh("run", "view", "--job", str(job_id), "--log")
    lines = [re.sub(r"^.*?\dZ ", "", line) for line in log.splitlines() if PATTERNS.search(line)]
    lines = [line for line in lines if not line.startswith(("##[", "shell:", "env:"))]
    print(f"\n=== {name}")
    for line in lines[-8:]:
        print("   ", line[:170])
