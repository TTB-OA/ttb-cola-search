"""FastAPI application entrypoint."""
from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .blob import close_blob
from .config import API_PREFIX, get_settings
from .db import close_pool, open_pool
from .routers import colas, health, images, reference, search

# psycopg's async driver cannot run on Windows' default ProactorEventLoop; select
# the SelectorEventLoop policy before uvicorn creates its loop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@asynccontextmanager
async def lifespan(app: FastAPI):
    await open_pool()
    try:
        yield
    finally:
        await close_pool()
        await close_blob()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.api_title,
        lifespan=lifespan,
        # Enable "Try it out" by default so users can execute endpoints
        # without first clicking the button.
        swagger_ui_parameters={"tryItOutEnabled": True},
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(reference.router, prefix=API_PREFIX)
    app.include_router(search.router, prefix=API_PREFIX)
    app.include_router(images.router, prefix=API_PREFIX)
    app.include_router(colas.router, prefix=API_PREFIX)

    spa_dir = _resolve_spa_dir(settings.spa_dir)
    if spa_dir is not None:
        _mount_spa(app, spa_dir)
    else:

        @app.get("/", include_in_schema=False)
        async def root() -> RedirectResponse:
            return RedirectResponse(url="/docs")

    return app


def _resolve_spa_dir(configured: str | None) -> Path | None:
    """Return the SPA build directory if configured and it contains index.html."""
    if not configured:
        return None
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path if (path / "index.html").is_file() else None


def _mount_spa(app: FastAPI, spa_dir: Path) -> None:
    """Serve the built Vite SPA single-origin.

    Hashed build assets are served from ``/assets``; any other non-API path
    falls back to ``index.html`` so client-side (BrowserRouter) routes resolve.
    Registered after the API routers, so ``/api/*`` and ``/docs`` take priority.
    """
    assets_dir = spa_dir / "assets"
    if assets_dir.is_dir():
        app.mount(
            "/assets", StaticFiles(directory=assets_dir), name="assets"
        )
    index_file = spa_dir / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        candidate = (spa_dir / full_path).resolve()
        if (
            full_path
            and spa_dir in candidate.parents
            and candidate.is_file()
        ):
            return FileResponse(candidate)
        return FileResponse(index_file)


app = create_app()
