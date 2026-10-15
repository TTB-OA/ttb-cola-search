"""Fields-only scan re-read vs. the full-prompt reading, per thinking level.

Samples sheets read with the full prompt on 2026-10-13 (ground truth), re-reads
each with ScanExtractor.extract_fields at every requested thinking level, and
reports per-field agreement plus token use. Writes nothing to the database.

Run from inside pipeline/:
    uv run python ../scripts/_diag_scan_fields_sample.py [n] [levels...]
    e.g. uv run python ../scripts/_diag_scan_fields_sample.py 200 default low
"""
import difflib
import json
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

from cola.core.pcr_env import get_conn
from cola.pipeline.image_ingest import build_azure_container_client
from cola.pipeline.scan_extract import (
    FIELDS_ONLY_FLAG_KEYS,
    ScanExtractor,
    default_max_edge,
)

N = int(sys.argv[1]) if len(sys.argv) > 1 else 200
LEVELS = sys.argv[2:] or ["default", "low"]
MODEL = "gemini-flash-latest"

conn = get_conn()
with conn.cursor() as cur:
    cur.execute(
        """--sql
        SELECT e.cola_id, e.file_name, i.blob_name,
               e.metadata->'form_flags', e.metadata->'usage'
          FROM "pcr-prod".cola_scan_extraction e
          JOIN "pcr-prod".cola_images i USING (cola_id, file_name)
         WHERE e.completed_on >= '2026-10-13' AND e.completed_on < '2026-10-14'
           AND e.extraction_model = %s
           AND i.blob_name IS NOT NULL
         ORDER BY md5(e.cola_id || e.file_name)
         LIMIT %s
        """,
        (MODEL, N),
    )
    sheets = cur.fetchall()
conn.close()
print(f"sample: {len(sheets)} sheets; levels: {LEVELS}")

container = build_azure_container_client()
extractors = {
    level: ScanExtractor(MODEL, default_max_edge(),
                         thinking_level=None if level == "default" else level)
    for level in LEVELS
}


def norm(key, value):
    if value is None:
        return None
    if key == "applicant_phone":
        return re.sub(r"\D", "", str(value)) or None
    if isinstance(value, bool):
        return value
    return re.sub(r"[^A-Z0-9@]+", " ", str(value).upper()).strip() or None


def verdict(key, truth, new):
    t, n = norm(key, truth), norm(key, new)
    if t is None and n is None:
        return "both_empty"
    if t is None:
        return "extra"
    if n is None:
        return "missed"
    if t == n:
        return "match"
    if key == "container_text" and difflib.SequenceMatcher(None, t, n).ratio() >= 0.85:
        return "match"
    return "differ"


def read(sheet):
    cola_id, file_name, blob_name, _, _ = sheet
    image = container.download_blob(blob_name).readall()
    return sheet, {level: ex.extract_fields(image) for level, ex in extractors.items()}


results = []
failures = 0
with ThreadPoolExecutor(max_workers=8) as pool:
    futures = [pool.submit(read, sheet) for sheet in sheets]
    for done, future in enumerate(as_completed(futures), 1):
        try:
            results.append(future.result())
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print("fail:", str(exc)[:200])
        if done % 25 == 0:
            print(f"  {done}/{len(sheets)}")

tallies = {level: defaultdict(Counter) for level in LEVELS}
tokens = {level: Counter() for level in ["truth", *LEVELS]}
diffs = []
for (cola_id, file_name, _, truth, truth_usage), by_level in results:
    truth = truth or {}
    for part, value in (truth_usage or {}).items():
        tokens["truth"][part] += value
    for level, (flags, _, usage) in by_level.items():
        for part, value in usage.items():
            tokens[level][part] += value
        for key in FIELDS_ONLY_FLAG_KEYS:
            v = verdict(key, truth.get(key), flags.get(key))
            tallies[level][key][v] += 1
            if v in ("differ", "missed", "extra"):
                diffs.append({"cola_id": cola_id, "level": level, "field": key,
                              "verdict": v, "truth": truth.get(key),
                              "new": flags.get(key)})

n = len(results)
print(f"\nread {n} sheets, {failures} failures")
print("\nmean tokens per sheet (prompt / output / thinking):")
for level, counter in tokens.items():
    print(f"  {level:8} {counter['prompt'] / n:7.0f} {counter['output'] / n:7.0f} "
          f"{counter['thinking'] / n:7.0f}")

cols = ("match", "both_empty", "missed", "extra", "differ")
for level in LEVELS:
    print(f"\n[{level}] field agreement vs full prompt ({n} sheets)")
    print(f"  {'field':20} " + " ".join(f"{c:>10}" for c in cols) + "   agree%")
    for key in FIELDS_ONLY_FLAG_KEYS:
        t = tallies[level][key]
        agree = 100 * (t["match"] + t["both_empty"]) / n
        print(f"  {key:20} " + " ".join(f"{t[c]:>10}" for c in cols) + f"   {agree:6.1f}")

out = Path("rpt") / f"scan_fields_sample_{datetime.now(UTC):%Y%m%dT%H%M%SZ}.jsonl"
out.write_text("\n".join(json.dumps(d, default=str) for d in diffs), encoding="utf-8")
print(f"\ndisagreements: {out}")
