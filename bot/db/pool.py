from __future__ import annotations

import logging

import asyncpg

log = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def init_pool(database_url: str) -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    log.info("Connecting to Postgres…")
    _pool = await asyncpg.create_pool(
        dsn=database_url,
        min_size=1,
        max_size=10,
        command_timeout=30,
        # Supabase + pgbouncer (transaction mode) rotates underlying
        # connections between queries, which invalidates asyncpg's
        # per-connection prepared statement cache. Disable the cache
        # to avoid InvalidCachedStatementError. Minor perf hit; fine
        # for a Discord bot.
        statement_cache_size=0,
    )
    log.info("Postgres pool ready.")
    return _pool


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized. Call init_pool() first.")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
