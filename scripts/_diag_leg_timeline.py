"""One-off: timelines of the OCR and materialize legs from one pipeline run.

Usage: uv run python scripts/_diag_leg_timeline.py RUN_ID
"""
import json
import re
import subprocess
import sys
from datetime import datetime

REPO = "TTB-OA/cola-data-scraping"
RUN = sys.argv[1]


def gh(*args):
    return subprocess.run(["gh", *args, "-R", REPO], capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout


STAMP = re.compile(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)\.\d+Z (.*)")
jobs = json.loads(gh("run", "view", RUN, "--json", "jobs"))["jobs"]

for leg, pattern in (
    ("cycle_backfill_analysis", r"\[IMAGE_ANALYSIS\]"),
    ("cycle_materialize", r"\[MATERIALIZE\]"),
):
    job = next(j for j in jobs if j["name"].startswith(leg))
    lines = []
    for raw in gh("run", "view", "--job", str(job["databaseId"]), "--log").splitlines():
        m = STAMP.search(raw)
        if m and re.search(pattern, m.group(2)):
            lines.append((datetime.fromisoformat(m.group(1)), m.group(2)))
    print(f"\n=== {leg}: {len(lines)} lines")
    if not lines:
        continue
    t0 = lines[0][0]
    seen = set()
    for t, text in lines:
        if text in seen:
            continue
        seen.add(text)
        if leg == "cycle_materialize" and "drained" in text and not text.endswith("000)"):
            continue
        print(f"  +{(t - t0).total_seconds() / 60:5.1f}m  {text[:150]}")
