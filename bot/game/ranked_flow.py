"""Ranked match orchestration: anti-exploit gating, skirmish, LP persistence.

Touches the DB but contains no Discord code — the pvp cog renders the result.
Pure ladder math lives in bot/game/ranked.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bot.db import queries
from bot.db.pool import get_pool
from bot.db.queries import RankedProfile
from bot.game import ranked
from bot.game.combat import SkirmishResult, simulate_skirmish
from bot.game.pvp_flow import LAMBS_RESPITE_COOLDOWN_KEY

# Anti-exploit pacing (PRD ranked §5).
RANKED_GLOBAL_COOLDOWN_KEY = "_ranked_global"
RANKED_GLOBAL_COOLDOWN = timedelta(minutes=30)
RANKED_TARGET_COOLDOWN = timedelta(hours=12)
RANKED_DAILY_CAP = 10


def _ranked_target_key(defender_id: int) -> str:
    return f"_ranked:{defender_id}"


@dataclass(frozen=True)
class RankedOutcome:
    skirmish: SkirmishResult | None = None
    error: str | None = None
    immune: bool = False
    cooldown_seconds: float | None = None
    attacker_won: bool = False
    attacker_lp_delta: int = 0
    defender_lp_delta: int = 0
    attacker_profile: RankedProfile | None = None   # post-match state
    defender_profile: RankedProfile | None = None
    attacker_was_in_placements: bool = False
    defender_was_in_placements: bool = False
    attacker_completed_placements: bool = False
    defender_completed_placements: bool = False


def _apply_match_result(p: RankedProfile, won: bool, lp_delta: int) -> int:
    """Mutate `p` for one ranked match. Returns the LP delta to record in the
    match log — always 0 while the player is still in placements."""
    if p.in_placements:
        p.placement_games += 1
        if won:
            p.placement_wins += 1
        if not p.in_placements:           # this match completed placements
            carry = ranked.season_mmr_carry(p.hidden_mmr)
            losses = p.placement_games - p.placement_wins
            p.lp = ranked.placement_starting_lp(p.placement_wins, losses, mmr_carry=carry)
            p.hidden_mmr = p.lp
        return 0                          # placement games never move LP directly

    old_lp = p.lp
    p.lp = max(0, p.lp + lp_delta)
    if won:
        p.wins += 1
        p.win_streak += 1
        p.loss_streak = 0
    else:
        p.losses += 1
        p.loss_streak += 1
        p.win_streak = 0
    p.hidden_mmr = p.lp
    return p.lp - old_lp


async def attempt_ranked_match(attacker_id: int, defender_id: int) -> RankedOutcome:
    """Run a ranked match. The cog renders whatever this returns."""
    if attacker_id == defender_id:
        return RankedOutcome(error="You can't queue a ranked match against yourself.")

    # Lamb's Respite — total PvP immunity covers the ranked ladder too.
    immune = await queries.check_cooldown(defender_id, LAMBS_RESPITE_COOLDOWN_KEY)
    if immune is not None:
        return RankedOutcome(immune=True)

    # Global ranked pacing — 30 minutes between any two ranked attacks.
    global_cd = await queries.check_cooldown(attacker_id, RANKED_GLOBAL_COOLDOWN_KEY)
    if global_cd is not None:
        return RankedOutcome(
            error="Your next ranked attack is still on cooldown.",
            cooldown_seconds=global_cd,
        )

    # Same-target lockout — at most one ranked match per opponent per 12h.
    target_cd = await queries.check_cooldown(attacker_id, _ranked_target_key(defender_id))
    if target_cd is not None:
        return RankedOutcome(
            error="You've already fought this player in ranked recently — "
            "rematches are limited to once every 12 hours.",
            cooldown_seconds=target_cd,
        )

    # Daily cap — 10 ranked attacks initiated per 24h.
    initiated = await queries.count_ranked_attacks_by(attacker_id, hours=24)
    if initiated >= RANKED_DAILY_CAP:
        return RankedOutcome(
            error=f"You've used all {RANKED_DAILY_CAP} of your ranked attacks for today. "
            "Come back tomorrow."
        )

    await queries.ensure_user(defender_id)

    attacker = await queries.get_user(attacker_id)
    defender = await queries.get_user(defender_id)
    if attacker is None or defender is None:
        return RankedOutcome(error="One of the players is missing a profile.")

    a_load = await queries.alive_loadout(attacker_id)
    if not a_load:
        return RankedOutcome(
            error="You have no alive champion equipped — check /menu for revive timers."
        )
    d_load = await queries.alive_loadout(defender_id)
    if not d_load:
        return RankedOutcome(error="Target has no alive champion equipped.")

    a_prof = await queries.ensure_ranked_profile(attacker_id)
    d_prof = await queries.ensure_ranked_profile(defender_id)

    # Ranked combat is pure loadout-vs-loadout: no gold stake, no shield
    # consumption, no consumable attack buffs — the ladder stays pay-to-skill-free.
    skirmish = simulate_skirmish(
        a_load, d_load,
        attacker_level=attacker.level,
        defender_level=defender.level,
        attacker_prestige=attacker.prestige,
        defender_prestige=defender.prestige,
        best_of=3,
    )
    attacker_won = skirmish.attacker_won

    # Effective tier indices for the Elo factor. A player still in placements
    # has no rank yet, so treat them as the same tier as their opponent
    # (gap 0) — placement matches never trigger punish-up or the farm lockout.
    a_idx = ranked.tier_index(a_prof.lp)
    d_idx = ranked.tier_index(d_prof.lp)
    if a_prof.in_placements and not d_prof.in_placements:
        a_idx = d_idx
    elif d_prof.in_placements and not a_prof.in_placements:
        d_idx = a_idx
    elif a_prof.in_placements and d_prof.in_placements:
        a_idx = d_idx = 0

    exchange = ranked.lp_exchange(
        a_idx, d_idx, attacker_won,
        attacker_win_streak=a_prof.win_streak,
        attacker_loss_streak=a_prof.loss_streak,
        defender_win_streak=d_prof.win_streak,
        defender_loss_streak=d_prof.loss_streak,
    )

    a_was_placing = a_prof.in_placements
    d_was_placing = d_prof.in_placements

    a_delta = _apply_match_result(a_prof, won=attacker_won, lp_delta=exchange.attacker_delta)
    d_delta = _apply_match_result(d_prof, won=not attacker_won, lp_delta=exchange.defender_delta)

    # Only the initiator resets their inactivity-decay timer.
    a_prof.last_ranked_attack_at = datetime.now(tz=timezone.utc)

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await queries.save_ranked_profile(a_prof, conn=conn)
            await queries.save_ranked_profile(d_prof, conn=conn)
            await queries.log_ranked_match(
                a_prof.season_id, attacker_id, defender_id, attacker_won,
                a_delta, d_delta, conn=conn,
            )
            await queries.set_cooldown(
                attacker_id, RANKED_GLOBAL_COOLDOWN_KEY, RANKED_GLOBAL_COOLDOWN, conn=conn
            )
            await queries.set_cooldown(
                attacker_id, _ranked_target_key(defender_id),
                RANKED_TARGET_COOLDOWN, conn=conn,
            )

    return RankedOutcome(
        skirmish=skirmish,
        attacker_won=attacker_won,
        attacker_lp_delta=a_delta,
        defender_lp_delta=d_delta,
        attacker_profile=a_prof,
        defender_profile=d_prof,
        attacker_was_in_placements=a_was_placing,
        defender_was_in_placements=d_was_placing,
        attacker_completed_placements=a_was_placing and not a_prof.in_placements,
        defender_completed_placements=d_was_placing and not d_prof.in_placements,
    )
