from __future__ import annotations

import logging

from discord.ext import tasks

from bot.db import queries

log = logging.getLogger(__name__)


@tasks.loop(minutes=5)
async def sweep_expired_trades() -> None:
    try:
        n = await queries.expire_old_trades()
        if n:
            log.info("Expired %d stale trade(s).", n)
    except Exception:
        log.exception("trade expiry sweep failed")
