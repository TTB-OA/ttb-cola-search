"""One-off: per-cycle OCR and detail stop lines from the last N scheduled runs.

Usage: uv run python scripts/_diag_ocr_detail_cycles.py [N]
"""
import json
import re
import subprocess
import sys

REPO = "TTB-OA/cola-data-scraping"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 12


def gh(*args):
    return subprocess.run(["gh", *args, "-R", REPO], capture_output=True, text=True,
                          encoding="utf-8", errors="replace").stdout


runs = json.loads(gh("run", "list", "--event", "schedule", "-L", str(N + 2),
                     "--json", "databaseId,status,createdAt"))
runs = [r for r in runs if r["status"] == "completed"][:N]

for run in runs:
    raw = gh("run", "view", str(run["databaseId"]), "--json", "jobs")
    if not raw.strip():
        continue
    jobs = {j["name"].split(" / ")[0]: j for j in json.loads(raw)["jobs"]}
    out = [run["createdAt"][5:16]]
    ocr = jobs.get("cycle_backfill_analysis")
    if ocr:
        log = gh("run", "view", "--job", str(ocr["databaseId"]), "--log")
        stop = re.search(r"stopping: [^(]*\((days=\d+ records=\d+ elapsed=[\d.]+m)\)", log)
        failed = len(re.findall(r"batch of \d+ FAILED", log))
        out.append(f"OCR {stop.group(1) if stop else 'no stop line'} hung={failed}")
    detail = jobs.get("cycle_backfill_detail")
    if detail:
        log = gh("run", "view", "--job", str(detail["databaseId"]), "--log")
        stop = re.search(r"\[DETAIL_FILL\] stopping: [^(]*\((days=\d+ records=\d+ elapsed=[\d.]+m)\)", log)
        out.append(f"detail[{detail.get('conclusion')}] {stop.group(1) if stop else 'no stop line'}")
    print("  ".join(out))
