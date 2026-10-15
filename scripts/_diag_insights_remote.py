import asyncio, os, sys, time
sys.path.insert(0, "/app/src")
from azure.identity.aio import DefaultAzureCredential
from azure.monitor.query import LogsBatchQuery
from azure.monitor.query.aio import LogsQueryClient
from api import insights

async def main():
    ws = os.environ["LOG_ANALYTICS_WORKSPACE_ID"]
    cred = DefaultAzureCredential()
    client = LogsQueryClient(cred)
    span = insights.RANGES["30d"]
    qs = insights._queries(insights._BUCKETS["30d"])
    t = time.perf_counter()
    await cred.get_token("https://api.loganalytics.io/.default")
    print("token", round(time.perf_counter() - t, 1), flush=True)
    t = time.perf_counter()
    r = await client.query_workspace(ws, "print 1", timespan=span)
    print("print1", round(time.perf_counter() - t, 1), flush=True)
    for name in ("totals", "map_mode_usage", "latency_over_time"):
        t = time.perf_counter()
        r = await client.query_workspace(ws, qs[name], timespan=span)
        print("single", name, round(time.perf_counter() - t, 1), flush=True)
    t = time.perf_counter()
    rs = await client.query_batch([LogsBatchQuery(workspace_id=ws, query=q, timespan=span) for q in qs.values()])
    print("batch23", round(time.perf_counter() - t, 1), sum(1 for x in rs if getattr(x, "tables", None) is None), "failed", flush=True)
    async def one(n, q):
        t0 = time.perf_counter()
        await client.query_workspace(ws, q, timespan=span)
        return n, round(time.perf_counter() - t0, 1)
    t = time.perf_counter()
    out = await asyncio.gather(*(one(n, q) for n, q in qs.items()))
    print("gather23", round(time.perf_counter() - t, 1), sorted(out, key=lambda x: -x[1])[:5], flush=True)
    await client.close()
    await cred.close()

asyncio.run(main())
