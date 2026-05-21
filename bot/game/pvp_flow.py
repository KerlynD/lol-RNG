"""End-to-end PvP resolution: loads loadouts + shields, runs combat,
persists outcome. Used by /attack and by every action with triggers_pvp=True.
"""
from __future__ import annotations

from dataclasses import dataclass

from bot.db import queries
from bot.db.pool import get_pool
from bot.game.combat import SkirmishResult, simulate_skirmish

PVP_ATTACKS_RECEIVED_CAP = 3
PVP_CAP_WINDOW_HOURS = 24

# Default share of defender's gold transferred to the winner (action-triggered).
DEFAULT_PVP_GOLD_STAKE_PCT = 0.10
PVP_GOLD_MIN = 25
PVP_GOLD_MAX_PER_ENCOUNTER = 5000

WORLD_ENDER_COOLDOWN_KEY = "_world_ender_active"
LAMBS_RESPITE_COOLDOWN_KEY = "_lambs_respite"


@dataclass(frozen=True)
class PvpOutcome:
    skirmish: SkirmishResult
    gold_transferred: int
    capped: bool                   # defender was rested
    immune: bool                   # defender had lambs-respite
    auto_tied: bool                # defender consumed kindred_passive
    error: str | None = None       # set when a precondition failed


async def attempt_pvp(
    attacker_id: int,
    defender_id: int,
    *,
    gold_stake_pct: float | None = None,
) -> PvpOutcome:
    """Run a PvP encounter. Caller decorates the message — this is engine-level."""
    if attacker_id == defender_id:
        return PvpOutcome(
            skirmish=None,  # type: ignore[arg-type]
            gold_transferred=0,
            capped=False,
            immune=False,
            auto_tied=False,
            error="You can't attack yourself.",
        )

    # Lambs Respite — total PvP immunity.
    immune_remaining = await queries.check_cooldown(defender_id, LAMBS_RESPITE_COOLDOWN_KEY)
    if immune_remaining is not None:
        return PvpOutcome(
            skirmish=None,  # type: ignore[arg-type]
            gold_transferred=0,
            capped=False,
            immune=True,
            auto_tied=False,
        )

    # PvP cap (PRD §5.4). World-Ender on the *attacker* lets them bypass cap *against them*,
    # not against defenders — so the standard cap on the defender always applies.
    received = await queries.count_recent_attacks_received(defender_id, hours=PVP_CAP_WINDOW_HOURS)
    if received >= PVP_ATTACKS_RECEIVED_CAP:
        return PvpOutcome(
            skirmish=None,  # type: ignore[arg-type]
            gold_transferred=0,
            capped=True,
            immune=False,
            auto_tied=False,
        )

    await queries.ensure_user(defender_id)

    attacker = await queries.get_user(attacker_id)
    defender = await queries.get_user(defender_id)
    if attacker is None or defender is None:
        return PvpOutcome(
            skirmish=None,  # type: ignore[arg-type]
            gold_transferred=0,
            capped=False,
            immune=False,
            auto_tied=False,
            error="One of the players is missing a profile.",
        )

    a_load = await queries.alive_loadout(attacker_id)
    d_load = await queries.alive_loadout(defender_id)
    if not a_load:
        return PvpOutcome(
            skirmish=None,  # type: ignore[arg-type]
            gold_transferred=0,
            capped=False,
            immune=False,
            auto_tied=False,
            error="You have no alive champions equipped — check /menu for revive timers.",
        )
    if not d_load:
        return PvpOutcome(
            skirmish=None,  # type: ignore[arg-type]
            gold_transferred=0,
            capped=False,
            immune=False,
            auto_tied=False,
            error="Target has no alive champions equipped.",
        )

    inv = await queries.get_inventory(defender_id)
    shields = {
        k: inv.get(k, 0)
        for k in ("shield_physical", "shield_magic", "aegis", "stasis")
    }
    auto_tied = inv.get("kindred_passive", 0) > 0

    # red_buff: consume now (atomic) and apply +20% attacker Power.
    attacker_inv = await queries.get_inventory(attacker_id)
    red_buff_active = False
    if attacker_inv.get("red_buff", 0) > 0:
        consumed = await queries.consume_item(attacker_id, "red_buff", 1)
        red_buff_active = bool(consumed)

    skirmish = simulate_skirmish(
        a_load, d_load,
        attacker_level=attacker.level,
        defender_level=defender.level,
        attacker_prestige=attacker.prestige,
        defender_prestige=defender.prestige,
        attacker_power_multiplier=(1.2 if red_buff_active else 1.0),
        defender_shields=shields,
    )

    # Compute gold stake
    pool = get_pool()
    stake_pct = gold_stake_pct if gold_stake_pct is not None else DEFAULT_PVP_GOLD_STAKE_PCT
    raw_gold = max(PVP_GOLD_MIN, int(defender.gold * stake_pct))
    raw_gold = min(raw_gold, defender.gold, PVP_GOLD_MAX_PER_ENCOUNTER)
    gold_xfer = raw_gold if not auto_tied else 0  # passive tie: no payout, no consumption of attacks

    # World-Ender doubles attacker payouts.
    we_active = await queries.check_cooldown(attacker_id, WORLD_ENDER_COOLDOWN_KEY)
    if we_active is not None and not auto_tied:
        gold_xfer *= 2
        gold_xfer = min(gold_xfer, defender.gold)

    final_attacker_won = skirmish.attacker_won and not auto_tied

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Persist shield consumption (decrement only those consumed).
            current_inv = await queries.get_inventory(defender_id)
            for s_type in ("shield_physical", "shield_magic", "aegis", "stasis"):
                consumed = current_inv.get(s_type, 0) - shields.get(s_type, 0)
                if consumed > 0:
                    await queries.consume_item(defender_id, s_type, consumed, conn=conn)

            if auto_tied:
                # consume one kindred_passive
                await queries.consume_item(defender_id, "kindred_passive", 1, conn=conn)
            else:
                # Persist gold transfer
                if final_attacker_won and gold_xfer > 0:
                    await queries.add_gold(defender_id, -gold_xfer, conn=conn)
                    await queries.add_gold(attacker_id, gold_xfer, conn=conn)
                outcome = "attacker_win" if final_attacker_won else "defender_win"
                await queries.log_pvp(
                    attacker_id, defender_id, outcome, gold_xfer if final_attacker_won else 0,
                    conn=conn,
                )

    # If auto_tied, do not return the skirmish with a "winner"; signal a forced tie.
    return PvpOutcome(
        skirmish=skirmish,
        gold_transferred=gold_xfer if final_attacker_won else 0,
        capped=False,
        immune=False,
        auto_tied=auto_tied,
    )
