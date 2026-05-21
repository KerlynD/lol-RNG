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
from bot.game.pve.souls import (
    SOUL_DROP_TO_TYPE,
    activate_soul,
    apply_camp_win_bonuses,
)

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

    # Consume red_buff_primed if present (+10% win pct). Manual activation
    # required — players prime via the /inventory button.
    red_buff_active = False
    inv_red = await queries.get_item_qty(user.discord_id, "red_buff_primed")
    if inv_red > 0:
        if await queries.consume_item(user.discord_id, "red_buff_primed", 1):
            red_buff_active = True

    fight = resolve_camp_fight(champ, camp, red_buff=red_buff_active, rng=rng)

    scaled_gold = (
        gold_payout(camp.base_gold, user.level, user.prestige)
        if fight.won
        else fight.gold_delta            # already negative
    )
    xp_award = camp.base_xp if fight.won else 0
    xp_result = apply_xp(user.xp, user.level, xp_award)

    # On win: apply soul-based bonus drops (Mountain/Chemtech/Hextech).
    final_drops: list[tuple[str, int]] = list(fight.drops)
    if fight.won:
        final_drops = await apply_camp_win_bonuses(user.discord_id, final_drops, rng=rng)

    # Hunt cooldown is already set at /hunt-camp invocation to prevent spam;
    # we surface the existing remaining time for display.
    existing_remaining = await queries.check_cooldown(user.discord_id, HUNT_CAMP_KEY)
    cd_remaining_display = int(existing_remaining) if existing_remaining else 0

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if scaled_gold:
                await queries.add_gold(user.discord_id, scaled_gold, conn=conn)
            if xp_award:
                await queries.set_user_level_xp(
                    user.discord_id, xp_result.new_level, xp_result.new_xp, conn=conn
                )
            for item_type, qty in final_drops:
                await queries.add_item(user.discord_id, item_type, qty, conn=conn)
            if fight.respawn_seconds > 0:
                await queries.kill_champion(
                    user.discord_id, champ.id,
                    timedelta(seconds=fight.respawn_seconds), conn=conn,
                )

    # Auto-activate any dragon souls that just dropped (outside the txn — the
    # soul lives in a cooldown row, not the inventory).
    for item_type, _qty in final_drops:
        soul_type = SOUL_DROP_TO_TYPE.get(item_type)
        if soul_type:
            await activate_soul(user.discord_id, soul_type)

    # Rebuild the fight CampFightResult to surface the bonus drops in the embed.
    fight_with_bonus = CampFightResult(
        won=fight.won,
        win_pct=fight.win_pct,
        gold_delta=fight.gold_delta,
        drops=final_drops if fight.won else [],
        respawn_seconds=fight.respawn_seconds,
    )

    return EngageOutcome(
        fight=fight_with_bonus,
        gold_awarded=scaled_gold,
        xp_awarded=xp_award,
        leveled_up_to=xp_result.leveled_up_to,
        champ_killed=champ if fight.respawn_seconds > 0 else None,
        cooldown_seconds_set=cd_remaining_display,
    )


# run_camp_back_out removed — the hunt-camp cooldown is now set at /hunt-camp
# invocation, so backing out is purely a UI action with no DB side-effects.
