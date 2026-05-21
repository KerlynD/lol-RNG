"""Generic action executor. Every action command in bot/cogs/actions.py calls
run_action() — this enforces all the cross-cutting rules in one place:

- Level gates (PRD §3 — action tier ≤ user's unlocked tier)
- Loadout requirements (region / faction / specific champion / min tier)
- Cooldown checks
- Synergy bonuses (PRD §4 — active at L10+)
- Drop table rolls
- Atomic persistence of gold + xp + inventory + cooldown
"""
from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass

from bot.db import queries
from bot.db.pool import get_pool
from bot.db.queries import Champion, LoadoutEntry, User
from bot.game.actions.registry import ActionSpec, get_spec
from bot.game.economy import gold_payout
from bot.game.leveling import apply_xp, unlocks_for


# Reasons a run can fail before payout. Each is user-facing.
@dataclass(frozen=True)
class ActionFailure:
    reason: str
    seconds_remaining: float | None = None  # set for cooldown failures


@dataclass(frozen=True)
class ActionSuccess:
    spec: ActionSpec
    gold_awarded: int
    xp_awarded: int
    drops: list[tuple[str, int]]      # (item_type, qty)
    leveled_up_to: int | None
    synergy_bonus_applied: bool


# Eligibility status used by the /menu dashboard.
ELIGIBLE = "available"
COOLDOWN = "cooldown"
LEVEL_LOCKED = "level_locked"
LOADOUT_LOCKED = "loadout_locked"


@dataclass(frozen=True)
class ActionAvailability:
    status: str                       # one of ELIGIBLE / COOLDOWN / LEVEL_LOCKED / LOADOUT_LOCKED
    spec: ActionSpec
    seconds_remaining: float | None = None
    chosen_champ_name: str | None = None
    missing_requirement: str | None = None
    required_level: int | None = None


def check_eligibility(
    spec: ActionSpec,
    user_level: int,
    loadout: list[LoadoutEntry],
    cooldowns: dict[str, float],
) -> ActionAvailability:
    """Pure check (no DB writes, no side effects). Used by /menu."""
    from bot.game.leveling import unlocks_for
    unlocks = unlocks_for(user_level)

    if spec.tier > unlocks.max_action_tier:
        return ActionAvailability(
            status=LEVEL_LOCKED,
            spec=spec,
            required_level=_min_level_for_tier(spec.tier),
        )

    chosen = _check_loadout_requirement(spec, loadout)
    needs_champ = (
        spec.required_champion is not None
        or spec.required_region is not None
        or spec.required_factions
        or spec.min_champ_tier > 0
    )
    if needs_champ and chosen is None:
        return ActionAvailability(
            status=LOADOUT_LOCKED,
            spec=spec,
            missing_requirement=_loadout_requirement_text(spec),
        )

    remaining = cooldowns.get(spec.key)
    if remaining is not None:
        return ActionAvailability(
            status=COOLDOWN,
            spec=spec,
            seconds_remaining=remaining,
            chosen_champ_name=chosen.name if chosen else None,
        )

    return ActionAvailability(
        status=ELIGIBLE,
        spec=spec,
        chosen_champ_name=chosen.name if chosen else None,
    )


def _loadout_requirement_text(spec: ActionSpec) -> str:
    if spec.required_champion:
        return spec.required_champion
    parts: list[str] = []
    if spec.required_region:
        parts.append(spec.required_region)
    if spec.required_factions:
        parts.append("/".join(spec.required_factions))
    if spec.min_champ_tier > 0:
        parts.append(f"T{spec.min_champ_tier}+")
    return ", ".join(parts) if parts else "any champion"


def _check_loadout_requirement(
    spec: ActionSpec, loadout: list[LoadoutEntry]
) -> Champion | None:
    """Return the first equipped champ that satisfies the action's requirement,
    or None if no champ in the loadout qualifies."""

    # If spec requires a specific champion, only that name will do.
    if spec.required_champion:
        for entry in loadout:
            if entry.champion.name.lower() == spec.required_champion.lower():
                return entry.champion
        return None

    candidates = [e.champion for e in loadout]

    if spec.required_region:
        candidates = [c for c in candidates if c.region == spec.required_region]

    if spec.required_factions:
        wanted = set(spec.required_factions)
        candidates = [c for c in candidates if wanted.intersection(c.factions)]

    if spec.min_champ_tier > 0:
        candidates = [c for c in candidates if c.tier >= spec.min_champ_tier]

    if not candidates:
        # No requirement at all means any equipped champ qualifies.
        if (
            not spec.required_region
            and not spec.required_factions
            and spec.min_champ_tier == 0
        ):
            return loadout[0].champion if loadout else None
        return None

    # Prefer the highest-tier qualifying champion.
    candidates.sort(key=lambda c: c.tier, reverse=True)
    return candidates[0]


def _synergy_multiplier(loadout: list[LoadoutEntry], user_level: int) -> float:
    if user_level < 10:
        return 1.0
    if not loadout:
        return 1.0
    mult = 1.0
    regions = Counter(e.champion.region for e in loadout if e.champion.region)
    if any(c >= 2 for c in regions.values()):
        mult *= 1.10
    factions_flat = Counter()
    for e in loadout:
        for f in e.champion.factions:
            factions_flat[f] += 1
    if any(c >= 3 for c in factions_flat.values()):
        mult *= 1.10
    damage = Counter(e.champion.damage_type for e in loadout)
    if any(c >= 2 for c in damage.values()):
        mult *= 1.05
    return mult


def _roll_drops(spec: ActionSpec, rng: random.Random) -> list[tuple[str, int]]:
    drops: list[tuple[str, int]] = []
    for item_type, probability in spec.drop_table:
        if probability >= 1.0:
            drops.append((item_type, 1))
        elif rng.random() < probability:
            drops.append((item_type, 1))
    return drops


async def run_action(
    user: User,
    action_key: str,
    *,
    bypass_cooldown: bool = False,
    rng: random.Random | None = None,
) -> ActionSuccess | ActionFailure:
    spec = get_spec(action_key)
    rng = rng or random

    unlocks = unlocks_for(user.level)
    if spec.tier > unlocks.max_action_tier:
        return ActionFailure(
            reason=(
                f"You need level {_min_level_for_tier(spec.tier)} to use {spec.name} "
                f"(Tier {spec.tier} action; you're Level {user.level})."
            )
        )

    loadout = await queries.get_loadout(user.discord_id)
    chosen_champ = _check_loadout_requirement(spec, loadout)
    needs_champ = (
        spec.required_champion is not None
        or spec.required_region is not None
        or spec.required_factions
        or spec.min_champ_tier > 0
    )
    if needs_champ and chosen_champ is None:
        return ActionFailure(reason=_loadout_requirement_error(spec))

    if not bypass_cooldown:
        remaining = await queries.check_cooldown(user.discord_id, spec.key)
        if remaining is not None:
            return ActionFailure(
                reason=f"{spec.name} is on cooldown.",
                seconds_remaining=remaining,
            )

    synergy = _synergy_multiplier(loadout, user.level)
    base_scaled = gold_payout(spec.base_gold, user.level, user.prestige)
    gold_awarded = int(round(base_scaled * synergy))
    xp_awarded = int(round(spec.base_xp * synergy))
    drops = _roll_drops(spec, rng)
    xp_result = apply_xp(user.xp, user.level, xp_awarded)

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if gold_awarded:
                await queries.add_gold(user.discord_id, gold_awarded, conn=conn)
            await queries.set_user_level_xp(
                user.discord_id, xp_result.new_level, xp_result.new_xp, conn=conn
            )
            for item_type, qty in drops:
                await queries.add_item(user.discord_id, item_type, qty, conn=conn)
            if not bypass_cooldown:
                await queries.set_cooldown(
                    user.discord_id, spec.key, spec.cooldown, conn=conn
                )

    return ActionSuccess(
        spec=spec,
        gold_awarded=gold_awarded,
        xp_awarded=xp_awarded,
        drops=drops,
        leveled_up_to=xp_result.leveled_up_to,
        synergy_bonus_applied=(synergy > 1.0),
    )


def _loadout_requirement_error(spec: ActionSpec) -> str:
    if spec.required_champion:
        return f"{spec.name} requires **{spec.required_champion}** equipped."
    parts: list[str] = []
    if spec.required_region:
        parts.append(f"a champion from **{spec.required_region}**")
    if spec.required_factions:
        parts.append(f"a champion from one of: **{', '.join(spec.required_factions)}**")
    if spec.min_champ_tier > 0:
        parts.append(f"a champion of at least **Tier {spec.min_champ_tier}**")
    if not parts:
        return f"{spec.name} requires a qualifying champion equipped."
    return f"{spec.name} requires " + " and ".join(parts) + " in your loadout."


def _min_level_for_tier(tier: int) -> int:
    # Mirrors leveling.LEVEL_UNLOCKS without reimporting structure.
    return {1: 1, 2: 1, 3: 5, 4: 10, 5: 15, 6: 20, 7: 25}.get(tier, 1)
