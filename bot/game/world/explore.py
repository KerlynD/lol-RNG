"""Region exploration runner (v3 Phase 5).

`/explore` is folded into the /adventure hub as a button — it explores the
*current* region. This module maps a world region to its encounter pool and
resolves the encounter (combat / treasure / lore), persisting the outcome.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import timedelta

from bot.db import queries
from bot.game.champions.abilities import progress_win_bonus
from bot.game.champions.leveling import EXPLORE_LEAD_FACTOR, EXPLORE_PASSIVE_SHARE
from bot.game.champions.xp import award_champ_xp
from bot.game.combat import power_score
from bot.game.economy import gold_payout
from bot.game.leveling import apply_xp
from bot.game.pve.combat import (
    DEFAULT_RESPAWN_SEC,
    FAIL_GOLD_PCT,
    PVE_WIN_PCT_BY_DIFF,
    RESPAWN_DURATION_SEC,
    WEAKNESS_BONUS_PCT,
)
from bot.game.pve.encounters import (
    REGIONS,
    CombatEncounter,
    TreasureEncounter,
)

EXPLORE_COOLDOWN = timedelta(hours=3)

# world region_key -> encounters.REGIONS keys (Piltover & Zaun merges two).
EXPLORE_REGION_MAP: dict[str, tuple[str, ...]] = {
    "bandle_city": ("Bandle City",),
    "demacia": ("Demacia",),
    "freljord": ("Freljord",),
    "ionia": ("Ionia",),
    "piltover_zaun": ("Piltover", "Zaun"),
    "bilgewater": ("Bilgewater",),
    "shadow_isles": ("Shadow Isles",),
    "ixtal": ("Ixtal",),
    "shurima": ("Shurima",),
    "noxus": ("Noxus",),
    "targon": ("Targon",),
    "void": ("Void",),
}


@dataclass
class ExploreResult:
    title: str
    description: str
    color: int
    champ_died: bool = False
    lore_unlocked: bool = False


def explore_pool(region_key: str) -> tuple:
    pool: list = []
    for enc_key in EXPLORE_REGION_MAP.get(region_key, ()):
        pool.extend(REGIONS.get(enc_key, ()))
    return tuple(pool)


async def run_explore(user, region_key: str, rng: random.Random | None = None) -> ExploreResult:
    """Resolve one exploration of `region_key`, persisting the outcome."""
    rng = rng or random.Random()
    pool = explore_pool(region_key)
    if not pool:
        return ExploreResult(
            title="Nothing here",
            description="This region holds no secrets to explore yet.",
            color=0x607D8B,
        )

    loadout = await queries.alive_loadout(user.discord_id)
    lead_entry = (
        max(loadout, key=lambda e: power_score(e.champion)) if loadout else None
    )

    encounter = rng.choice(pool)
    # Combat needs a living champion — without one, fall back to a safe vignette.
    if isinstance(encounter, CombatEncounter) and lead_entry is None:
        safe = [e for e in pool if not isinstance(e, CombatEncounter)]
        if safe:
            encounter = rng.choice(safe)

    if isinstance(encounter, CombatEncounter):
        return await _resolve_combat(user, encounter, lead_entry, loadout, rng)
    if isinstance(encounter, TreasureEncounter):
        return await _resolve_treasure(user, encounter, rng)
    return await _resolve_lore(user, encounter)


async def _resolve_combat(user, enc, lead_entry, loadout, rng) -> ExploreResult:
    mob = enc.mob
    lead = lead_entry.champion
    diff = max(-4, min(4, lead.tier - mob.tier))
    win_pct = PVE_WIN_PCT_BY_DIFF[diff]
    if mob.weak_to and lead.damage_type == mob.weak_to:
        win_pct += WEAKNESS_BONUS_PCT
    win_pct += progress_win_bonus(lead_entry.progress)
    win_pct = max(1.0, min(99.0, win_pct))
    won = rng.uniform(0, 100) < win_pct

    if won:
        gold = gold_payout(mob.base_gold, user.level, user.prestige)
        xp_result = apply_xp(user.xp, user.level, mob.base_xp)
        await queries.add_gold(user.discord_id, gold)
        await queries.set_user_level_xp(
            user.discord_id, xp_result.new_level, xp_result.new_xp
        )
        # Menial champ XP for the loadout (explore is a minor source).
        levelups = await award_champ_xp(
            user.discord_id, loadout, lead.id,
            round(mob.base_xp * EXPLORE_LEAD_FACTOR), EXPLORE_PASSIVE_SHARE,
        )
        level_line = (
            f"\n✨ **Level up → {xp_result.leveled_up_to}**"
            if xp_result.leveled_up_to else ""
        )
        champ_line = ""
        if levelups:
            names = ", ".join(lu.champion.name for lu in levelups)
            champ_line = f"\n🆙 **{names}** levelled up — see `/champion`."
        return ExploreResult(
            title="Exploration — Victory",
            description=(
                f"{enc.flavor}\n\n**{lead.name}** dispatches the **{mob.name}**.\n"
                f"Gold **+{gold:,}** · XP **+{mob.base_xp}**{level_line}{champ_line}"
            ),
            color=0x4CAF50,
        )

    respawn = RESPAWN_DURATION_SEC.get(diff, DEFAULT_RESPAWN_SEC)
    penalty = min(user.gold, int(mob.base_gold * FAIL_GOLD_PCT))
    await queries.add_gold(user.discord_id, -penalty)
    await queries.kill_champion(
        user.discord_id, lead.id, timedelta(seconds=respawn)
    )
    return ExploreResult(
        title="Exploration — Defeated",
        description=(
            f"{enc.flavor}\n\n**{lead.name}** falls to the **{mob.name}**.\n"
            f"Gold lost: **{penalty}** · {lead.name} dies for **{respawn // 60} min**."
        ),
        color=0xF44336,
        champ_died=True,
    )


async def _resolve_treasure(user, enc, rng) -> ExploreResult:
    gold = gold_payout(enc.base_gold, user.level, user.prestige)
    await queries.add_gold(user.discord_id, gold)
    drop_line = ""
    if enc.bonus_drop and rng.random() < enc.drop_chance:
        await queries.add_item(user.discord_id, enc.bonus_drop, 1)
        label = enc.bonus_drop.replace("_", " ").title()
        drop_line = f"\nBonus drop: **{label} ×1**"
    return ExploreResult(
        title="Exploration — Treasure",
        description=f"{enc.flavor}\n\nGold **+{gold:,}**{drop_line}",
        color=0xFFC107,
    )


async def _resolve_lore(user, enc) -> ExploreResult:
    newly = await queries.unlock_lore(user.discord_id, enc.lore_key)
    desc = f"{enc.flavor}\n\n{enc.lore_text}"
    if newly:
        desc += "\n\n_Saved to your `/lore` collection._"
    return ExploreResult(
        title="Exploration — Lore" + ("" if newly else " (familiar)"),
        description=desc,
        color=0x9C27B0,
        lore_unlocked=newly,
    )
