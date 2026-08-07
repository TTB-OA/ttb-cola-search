"""FastAPI application entrypoint."""
from __future__ import annotations

import asyncio
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from psycopg.errors import QueryCanceled

from .analytics import (
    EVENT_BY_ROUTE,
    emit,
    route_key,
    session_id_from,
    shape_detail_event,
    shape_image_search_event,
    shape_search_event,
    shape_similar_event,
)
from .blob import close_blob
from .config import API_PREFIX, Settings, get_settings
from .db import close_pool, open_pool
from .insights import close_insights
from .routers import (
    colas,
    coverage,
    events,
    health,
    images,
    insights,
    reference,
    search,
)
from .telemetry import configure_telemetry

# psycopg's async driver cannot run on Windows' default ProactorEventLoop; select
# the SelectorEventLoop policy before uvicorn creates its loop.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_telemetry(get_settings())
    await open_pool()
    try:
        yield
    finally:
        await close_pool()
        await close_blob()
        await close_insights()


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

    @app.middleware("http")
    async def _analytics(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        _record_event(request, response.status_code, started, settings)
        return response

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(reference.router, prefix=API_PREFIX)
    app.include_router(coverage.router, prefix=API_PREFIX)
    app.include_router(search.router, prefix=API_PREFIX)
    app.include_router(images.router, prefix=API_PREFIX)
    app.include_router(colas.router, prefix=API_PREFIX)
    app.include_router(events.router, prefix=API_PREFIX)
    app.include_router(insights.router, prefix=API_PREFIX)

    @app.exception_handler(QueryCanceled)
    async def _statement_timeout(request: Request, exc: QueryCanceled) -> JSONResponse:
        return JSONResponse(
            status_code=504,
            content={"detail": "The search took too long. Narrow your filters and try again."},
        )

    spa_dir = _resolve_spa_dir(settings.spa_dir)
    if spa_dir is not None:
        _mount_spa(app, spa_dir)
    else:

        @app.get("/", include_in_schema=False)
        async def root() -> RedirectResponse:
            return RedirectResponse(url="/docs")

    return app


def _record_event(
    request: Request, status_code: int, started: float, settings: Settings
) -> None:
    """Emit a shaped product event for the handful of routes worth measuring."""
    try:
        route = request.scope.get("route")
        name = EVENT_BY_ROUTE.get(route_key(request.method, getattr(route, "path", "")))
        if name is None:
            return

        params = request.query_params
        attrs: dict[str, object] = {
            "session_id": session_id_from(
                request,
                trust_forwarded_for=settings.trust_forwarded_for,
                salt=settings.analytics_salt,
            ),
            # Not "origin": that is also the name of a search filter, and the
            # shaped attributes below would overwrite it.
            "event_source": "server",
            "status_code": status_code,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        }

        if name == "search_performed":
            attrs |= shape_search_event(
                params, capture_query_text=settings.analytics_capture_query_text
            )
        elif name == "detail_viewed":
            attrs |= shape_detail_event(request.scope.get("path_params") or {})
        elif name == "similar_requested":
            attrs |= shape_similar_event(params)
        elif name == "image_search_performed":
            length = request.headers.get("content-length")
            attrs |= shape_image_search_event(
                int(length) if length and length.isdigit() else None,
                request.headers.get("content-type"),
            )

        attrs |= getattr(request.state, "analytics", {})
        emit(name, attrs)
    except Exception:  # noqa: BLE001 - analytics must never break a response
        pass


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
