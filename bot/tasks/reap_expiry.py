from __future__ import annotations

import logging

from discord.ext import tasks

from bot.db import queries

log = logging.getLogger(__name__)


@tasks.loop(hours=1)
async def sweep_expired_reap_marks() -> None:
    try:
        n = await queries.expire_old_reap_marks()
        if n:
            log.info("Expired %d reap mark(s).", n)
    except Exception:
        log.exception("reap expiry sweep failed")
