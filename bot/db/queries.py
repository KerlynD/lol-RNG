"""Data-access layer. Real queries land here as cogs grow."""
from __future__ import annotations

from bot.db.pool import get_pool


async def champion_count() -> int:
    p = get_pool()
    return await p.fetchval("SELECT COUNT(*) FROM champions")
