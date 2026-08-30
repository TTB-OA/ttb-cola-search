"""Async Postgres access with Microsoft Entra (token) or password auth.

A single :class:`~psycopg_pool.AsyncConnectionPool` is shared by the app. When
``POSTGRES_AUTH_METHOD=entra`` each new physical connection is opened with a
freshly-acquired Entra access token (scoped for Azure Database for PostgreSQL)
as its password, so long-lived pools survive token expiry.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

import certifi
from azure.identity.aio import DefaultAzureCredential
from psycopg import AsyncConnection, AsyncCursor
from psycopg.abc import QueryNoTemplate
from psycopg.rows import dict_row
from psycopg.sql import SQL, Identifier, Literal
from psycopg_pool import AsyncConnectionPool

from .config import Settings, get_settings

# Scope for AAD tokens used to authenticate to Azure Database for PostgreSQL.
# The resource is ossrdbms-aad.database.windows.net (equivalent to the Azure CLI
# `--resource-type oss-rdbms`); the ...postgres.azure.com identifier is not
# provisioned in all tenants and fails token acquisition with AADSTS500011.
PG_AAD_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"


class _TokenProvider:
    """Caches an Entra access token and refreshes it shortly before expiry."""

    def __init__(self) -> None:
        self._credential = DefaultAzureCredential()
        self._token: str | None = None
        self._expires_on: float = 0.0
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        async with self._lock:
            now = time.time()
            if self._token and now < self._expires_on - 300:
                return self._token
            token = await self._credential.get_token(PG_AAD_SCOPE)
            self._token = token.token
            self._expires_on = float(token.expires_on)
            return self._token

    async def close(self) -> None:
        await self._credential.close()


_token_provider: _TokenProvider | None = None


def _get_token_provider() -> _TokenProvider:
    global _token_provider
    if _token_provider is None:
        _token_provider = _TokenProvider()
    return _token_provider


class _EntraAsyncConnection(AsyncConnection):
    """Connection subclass that injects a fresh Entra token as the password."""

    @classmethod
    async def connect(cls, conninfo: str = "", **kwargs: Any):  # type: ignore[override]
        kwargs["password"] = await _get_token_provider().get_token()
        return await super().connect(conninfo, **kwargs)


def _base_kwargs(settings: Settings) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "host": settings.postgres_host,
        "port": settings.postgres_port,
        "dbname": settings.postgres_db,
        "user": settings.postgres_user,
        "sslmode": settings.postgres_sslmode,
        "connect_timeout": settings.postgres_connect_timeout,
        "row_factory": dict_row,
        "autocommit": True,
    }
    if settings.postgres_pgbouncer:
        # PgBouncer's default max_prepared_statements=0 cannot track psycopg's
        # automatic prepared statements across pooled server connections.
        kwargs["prepare_threshold"] = None
    if settings.postgres_sslrootcert:
        kwargs["sslrootcert"] = settings.postgres_sslrootcert
    elif settings.postgres_sslmode in ("verify-ca", "verify-full"):
        # libpq's default root.crt path usually doesn't exist; use the certifi
        # CA bundle, which includes the roots Azure Database for PostgreSQL uses.
        kwargs["sslrootcert"] = certifi.where()
    return kwargs


async def _configure(conn: AsyncConnection) -> None:
    """Set the search_path and statement timeout on every pooled connection."""
    settings = get_settings()
    async with conn.cursor() as cur:
        await cur.execute(
            SQL("SET search_path TO {}, public").format(
                Identifier(settings.postgres_schema)
            )
        )
        await cur.execute(
            SQL("SET statement_timeout TO {}").format(
                Literal(settings.postgres_statement_timeout_ms)
            )
        )


async def _set_local(cur: AsyncCursor[Any]) -> None:
    """Transaction-scoped form of :func:`_configure`, for PgBouncer.

    Under transaction pooling each statement can land on a different server
    connection, so session-level settings never survive; settings applied
    inside the transaction that runs the query do. Both go through one
    ``set_config`` statement to keep it to a single round trip.
    """
    settings = get_settings()
    await cur.execute(
        "SELECT set_config('search_path', %s, true), "
        "set_config('statement_timeout', %s, true)",
        [
            f'"{settings.postgres_schema}", public',
            str(settings.postgres_statement_timeout_ms),
        ],
    )


@asynccontextmanager
async def transaction_cursor() -> AsyncIterator[AsyncCursor[Any]]:
    """Cursor in an explicit transaction, so the settings apply to the query."""
    async with get_pool().connection() as conn, conn.transaction(), conn.cursor() as cur:
        if get_settings().postgres_pgbouncer:
            await _set_local(cur)
        yield cur


@asynccontextmanager
async def _cursor() -> AsyncIterator[AsyncCursor[Any]]:
    if get_settings().postgres_pgbouncer:
        async with transaction_cursor() as cur:
            yield cur
    else:
        async with get_pool().connection() as conn, conn.cursor() as cur:
            yield cur


_pool: AsyncConnectionPool | None = None


def _make_pool() -> AsyncConnectionPool:
    settings = get_settings()
    kwargs = _base_kwargs(settings)
    if settings.postgres_auth_method.lower() == "password":
        kwargs["password"] = settings.postgres_password
        connection_class: type[AsyncConnection] = AsyncConnection
    else:
        connection_class = _EntraAsyncConnection
    return AsyncConnectionPool(
        conninfo="",
        connection_class=connection_class,
        kwargs=kwargs,
        min_size=settings.postgres_pool_min,
        max_size=settings.postgres_pool_max,
        configure=None if settings.postgres_pgbouncer else _configure,
        open=False,
    )


def get_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = _make_pool()
    return _pool


async def open_pool() -> None:
    # Do not block application startup on the first physical connection.
    # The pool will connect lazily on demand, and /health already reports a
    # degraded database state when the backend is unreachable.
    await get_pool().open(wait=False)


async def close_pool() -> None:
    global _pool, _token_provider
    if _pool is not None:
        await _pool.close()
        _pool = None
    if _token_provider is not None:
        await _token_provider.close()
        _token_provider = None


async def fetch_all(query: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    async with _cursor() as cur:
        await cur.execute(cast(QueryNoTemplate, query), params)
        rows = await cur.fetchall()
        # row_factory=dict_row yields mapping rows at runtime; cast for static checkers.
        return cast(list[dict[str, Any]], rows)


async def fetch_one(query: str, params: list[Any] | None = None) -> dict[str, Any] | None:
    async with _cursor() as cur:
        await cur.execute(cast(QueryNoTemplate, query), params)
        row = await cur.fetchone()
        # row_factory=dict_row yields mapping rows at runtime; cast for static checkers.
        return cast(dict[str, Any] | None, row)
