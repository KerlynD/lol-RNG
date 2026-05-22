from __future__ import annotations

import logging

from discord.ext import tasks

from bot.db import queries
from bot.game.ranked import (
    DECAY_FLOOR_LP,
    DECAY_INACTIVITY_DAYS,
    DECAY_LP,
    DECAY_MIN_TIER_LP,
)

log = logging.getLogger(__name__)


@tasks.loop(hours=12)
async def decay_inactive_ranked() -> None:
    """Inactivity decay for Platinum+ players. The per-row last_decay_at guard
    makes this idempotent, so running twice a day costs at most one tick."""
    try:
        decayed = await queries.run_ranked_decay(
            DECAY_FLOOR_LP, DECAY_LP, DECAY_MIN_TIER_LP, DECAY_INACTIVITY_DAYS
        )
        if decayed:
            log.info("Ranked decay applied to %d profile(s).", len(decayed))
    except Exception:
        log.exception("ranked decay sweep failed")
