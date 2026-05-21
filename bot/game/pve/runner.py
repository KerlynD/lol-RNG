"""PVE runner — orchestrates engagement and back-out side effects."""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import timedelta

from bot.db import queries
from bot.db.pool import get_pool
from bot.db.queries import Champion, User
from bot.game.economy import gold_payout
from bot.game.leveling import apply_xp
from bot.game.pve.camps import CampSpec, cooldown_seconds
from bot.game.pve.combat import CampFightResult, resolve_camp_fight

HUNT_CAMP_KEY = "hunt-camp"


@dataclass(frozen=True)
class EngageOutcome:
    fight: CampFightResult
    gold_awarded: int
    xp_awarded: int
    leveled_up_to: int | None
    champ_killed: Champion | None
    cooldown_seconds_set: int


async def run_camp_engage(
    user: User,
    camp: CampSpec,
    champ: Champion,
    rng: random.Random | None = None,
) -> EngageOutcome:
    rng = rng or random

    # Consume red_buff if present (provides +10% win pct on engage).
    red_buff_active = False
    inv_red = await queries.get_item_qty(user.discord_id, "red_buff")
    if inv_red > 0:
        if await queries.consume_item(user.discord_id, "red_buff", 1):
            red_buff_active = True

    fight = resolve_camp_fight(champ, camp, red_buff=red_buff_active, rng=rng)

    scaled_gold = (
        gold_payout(camp.base_gold, user.level, user.prestige)
        if fight.won
        else fight.gold_delta            # already negative
    )
    xp_award = camp.base_xp if fight.won else 0
    xp_result = apply_xp(user.xp, user.level, xp_award)
    cd = cooldown_seconds(camp, rng=rng)

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if scaled_gold:
                await queries.add_gold(user.discord_id, scaled_gold, conn=conn)
            if xp_award:
                await queries.set_user_level_xp(
                    user.discord_id, xp_result.new_level, xp_result.new_xp, conn=conn
                )
            for item_type, qty in fight.drops:
                await queries.add_item(user.discord_id, item_type, qty, conn=conn)
            await queries.set_cooldown(
                user.discord_id, HUNT_CAMP_KEY, timedelta(seconds=cd), conn=conn
            )
            if fight.respawn_seconds > 0:
                await queries.kill_champion(
                    user.discord_id, champ.id,
                    timedelta(seconds=fight.respawn_seconds), conn=conn,
                )

    return EngageOutcome(
        fight=fight,
        gold_awarded=scaled_gold,
        xp_awarded=xp_award,
        leveled_up_to=xp_result.leveled_up_to,
        champ_killed=champ if fight.respawn_seconds > 0 else None,
        cooldown_seconds_set=cd,
    )


async def run_camp_back_out(
    user: User,
    camp: CampSpec,
    rng: random.Random | None = None,
) -> int:
    """Apply hunt-camp cooldown only. Returns cooldown duration in seconds."""
    rng = rng or random
    cd = cooldown_seconds(camp, rng=rng)
    await queries.set_cooldown(user.discord_id, HUNT_CAMP_KEY, timedelta(seconds=cd))
    return cd
