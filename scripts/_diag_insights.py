"""Time the analytics dashboard Log Analytics queries: full batch vs each panel alone.

DIAG_WORKSPACE (customerId) and DIAG_RANGE (default 30d) select the target.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from azure.identity.aio import AzureCliCredential  # noqa: E402
from azure.monitor.query import LogsBatchQuery  # noqa: E402
from azure.monitor.query.aio import LogsQueryClient  # noqa: E402

from api import insights  # noqa: E402

WORKSPACE = os.environ.get("DIAG_WORKSPACE", "fd51a879-c180-4a2d-9ac5-97ba20d8065c")
RANGE = os.environ.get("DIAG_RANGE", "30d")


async def main() -> None:
    from api.config import get_settings

    settings = get_settings().model_copy(update={"log_analytics_workspace_id": WORKSPACE})
    t0 = time.perf_counter()
    panels, failed = await insights.run_panels(settings, RANGE)
    print(f"run_panels: {time.perf_counter() - t0:.1f}s, {len(panels)} panels, failed={failed}")
    await insights.close_insights()
    if os.environ.get("DIAG_ONLY") == "run_panels":
        return

    cred = AzureCliCredential(process_timeout=60)
    client = LogsQueryClient(cred)
    timespan = insights.RANGES[RANGE]
    queries = insights._queries(insights._BUCKETS[RANGE])
    try:
        t0 = time.perf_counter()
        batch = [
            LogsBatchQuery(workspace_id=WORKSPACE, query=q, timespan=timespan, include_statistics=True)
            for q in queries.values()
        ]
        results = await client.query_batch(batch)
        print(f"batch of {len(batch)}: {time.perf_counter() - t0:.1f}s")
        for name, r in zip(queries, results):
            stats = getattr(r, "statistics", None) or {}
            q = stats.get("query", {})
            print(f"  {name:24s} exec={q.get('executionTime', '?')}s rows={len(r.tables[0].rows) if getattr(r, 'tables', None) else r}")

        for name, q in queries.items():
            t0 = time.perf_counter()
            r = await client.query_workspace(WORKSPACE, q, timespan=timespan)
            print(f"single {name:24s} {time.perf_counter() - t0:.1f}s rows={len(r.tables[0].rows)}")
    finally:
        await client.close()
        await cred.close()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
