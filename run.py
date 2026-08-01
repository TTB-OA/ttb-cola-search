"""Local launch entrypoint for the API.

On Windows the default asyncio ProactorEventLoop is incompatible with psycopg's
async driver. The uvicorn CLI creates its event loop before importing the app
module, so the policy must be set here, before uvicorn.run() is called.

Usage: uv run python run.py
"""
from __future__ import annotations

import asyncio
import os
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host=os.getenv("API_HOST", "127.0.0.1"),
        port=int(os.getenv("API_PORT", "8000")),
        app_dir="src",
        reload="--reload" in sys.argv,
        # uvicorn otherwise forces the Windows ProactorEventLoop, which psycopg's
        # async driver rejects; "none" leaves our SelectorEventLoop policy intact.
        loop="none",
    )
