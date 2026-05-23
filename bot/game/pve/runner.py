"""PVE runner — orchestrates engagement and back-out side effects."""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import timedelta

from bot.db import queries
from bot.db.pool import get_pool
from bot.db.queries import Champion, ChampProgress, LoadoutEntry, User
from bot.game.champions.abilities import progress_win_bonus
from bot.game.champions.leveling import (
    HUNT_LEAD_FACTOR,
    HUNT_PASSIVE_SHARE,
    apply_champ_xp,
    passive_xp,
)
from bot.game.economy import gold_payout
from bot.game.leveling import apply_xp
from bot.game.pve.camps import CampSpec
from bot.game.pve.combat import CampFightResult, fail_gold_pct, resolve_camp_fight
from bot.game.pve.souls import (
    SOUL_DROP_TO_TYPE,
    activate_soul,
    apply_camp_win_bonuses,
)

HUNT_CAMP_KEY = "hunt-camp"


@dataclass(frozen=True)
class ChampLevelUp:
    champion: Champion
    old_level: int
    new_level: int
    progress: ChampProgress      # post-level-up state
    is_lead: bool


@dataclass(frozen=True)
class EngageOutcome:
    fight: CampFightResult
    gold_awarded: int
    xp_awarded: int
    leveled_up_to: int | None
    champ_killed: Champion | None
    cooldown_seconds_set: int
    champ_xp_awarded: int = 0                 # champ XP given to the lead
    lead_progress: ChampProgress | None = None  # lead's post-fight progress
    champ_levelups: tuple[ChampLevelUp, ...] = ()


async def run_camp_engage(
    user: User,
    camp: CampSpec,
    champ_entry: LoadoutEntry,
    loadout: list[LoadoutEntry],
    rng: random.Random | None = None,
    reward_factor: float = 1.0,
) -> EngageOutcome:
    """Resolve a camp engagement. `reward_factor` (v3) scales win Gold/XP — it
    carries the backtracking decay so hunting an early region late pays less.

    On a win the lead champion earns champ XP; the rest of the alive loadout
    earns a small passive share. Champion levels are persisted here.
    """
    rng = rng or random
    champ = champ_entry.champion

    # Consume red_buff_primed if present (+10% win pct). Manual activation
    # required — players prime via the /inventory button.
    red_buff_active = False
    inv_red = await queries.get_item_qty(user.discord_id, "red_buff_primed")
    if inv_red > 0:
        if await queries.consume_item(user.discord_id, "red_buff_primed", 1):
            red_buff_active = True

    champ_bonus = progress_win_bonus(champ_entry.progress)
    fight = resolve_camp_fight(
        champ, camp, red_buff=red_buff_active, champ_bonus=champ_bonus, rng=rng
    )

    if fight.won:
        scaled_gold = int(
            gold_payout(camp.base_gold, user.level, user.prestige) * reward_factor
        )
        xp_award = max(1, int(camp.base_xp * reward_factor))
    else:
        # Losses now scale with level (matches win payouts) AND with how badly
        # you were outmatched — fail_gold_pct returns 0.5 at matched tier and
        # ramps to 1.0 four tiers down. Decay applies so backtracking still
        # softens stakes both ways.
        diff = max(-4, min(4, champ.tier - camp.tier))
        scaled_gold = -int(
            gold_payout(camp.base_gold, user.level, user.prestige)
            * fail_gold_pct(diff) * reward_factor
        )
        xp_award = 0
    xp_result = apply_xp(user.xp, user.level, xp_award)

    # On win: apply soul-based bonus drops (Mountain/Chemtech/Hextech).
    final_drops: list[tuple[str, int]] = list(fight.drops)
    if fight.won:
        final_drops = await apply_camp_win_bonuses(user.discord_id, final_drops, rng=rng)

    # Champion XP — win only. Lead gets the full share, the rest a small passive
    # trickle (only while in the loadout, which `loadout` already guarantees).
    lead_xp = round(camp.base_xp * HUNT_LEAD_FACTOR * reward_factor) if fight.won else 0
    pass_xp = passive_xp(lead_xp, HUNT_PASSIVE_SHARE) if lead_xp else 0
    champ_levelups: list[ChampLevelUp] = []
    progress_writes: list[tuple[int, ChampProgress]] = []
    lead_progress = champ_entry.progress
    if fight.won:
        for entry in loadout:
            is_lead = entry.champion.id == champ.id
            gain = lead_xp if is_lead else pass_xp
            result = apply_champ_xp(entry.progress, entry.champion.tier, gain)
            progress_writes.append((entry.champion.id, result.progress))
            if is_lead:
                lead_progress = result.progress
            if result.levels_gained > 0:
                champ_levelups.append(ChampLevelUp(
                    champion=entry.champion,
                    old_level=entry.progress.champ_level,
                    new_level=result.progress.champ_level,
                    progress=result.progress,
                    is_lead=is_lead,
                ))

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
            for champion_id, new_progress in progress_writes:
                await queries.set_champ_progress(
                    user.discord_id, champion_id, new_progress, conn=conn
                )
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
        champ_xp_awarded=lead_xp,
        lead_progress=lead_progress,
        champ_levelups=tuple(champ_levelups),
    )


# run_camp_back_out removed — the hunt-camp cooldown is now set at /hunt-camp
# invocation, so backing out is purely a UI action with no DB side-effects.
