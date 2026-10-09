"""One-off: run the reference count loaders against the live DB."""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv

load_dotenv()
from src.api.db import close_pool, open_pool  # noqa: E402
from src.api.routers import reference as ref  # noqa: E402


async def main() -> None:
    await open_pool()
    t = time.perf_counter()
    lookups = await ref._load_lookups()
    vc = lookups["varietal_counts"]
    print(f"lookups {time.perf_counter() - t:.2f}s: {len(lookups['varietals'])} varietals, {len(vc)} with records")
    print("  top varietals:", sorted(vc.items(), key=lambda kv: -kv[1])[:5])
    t = time.perf_counter()
    cc = await ref._load_class_counts()
    print(f"class counts {time.perf_counter() - t:.2f}s: {len(lookups['class_types'])} class types, {len(cc)} with records")
    print("  top class types:", sorted(cc.items(), key=lambda kv: -kv[1])[:5])
    await close_pool()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
