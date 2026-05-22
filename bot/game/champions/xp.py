"""Shared champ-XP award orchestration for the non-hunt PVE sources.

`/hunt-camp` awards champ XP inline inside its own transaction
(bot/game/pve/runner.py). World bosses, /explore and ambient encounters use
this helper instead. Touches the DB — not a pure module.
"""
from __future__ import annotations

from bot.db import queries
from bot.db.queries import LoadoutEntry
from bot.game.champions.leveling import apply_champ_xp, passive_xp
from bot.game.pve.runner import ChampLevelUp


async def award_champ_xp(
    user_id: int,
    loadout: list[LoadoutEntry],
    lead_champion_id: int,
    lead_xp: int,
    passive_share: float,
) -> list[ChampLevelUp]:
    """Grant champ XP to a loadout: the lead gets `lead_xp`, every other alive
    member gets a passive share. Persists each champion's progress. Returns the
    champions that levelled up (for a compact UI line)."""
    levelups: list[ChampLevelUp] = []
    for entry in loadout:
        is_lead = entry.champion.id == lead_champion_id
        gain = lead_xp if is_lead else passive_xp(lead_xp, passive_share)
        if gain <= 0:
            continue
        result = apply_champ_xp(entry.progress, entry.champion.tier, gain)
        await queries.set_champ_progress(user_id, entry.champion.id, result.progress)
        if result.levels_gained > 0:
            levelups.append(ChampLevelUp(
                champion=entry.champion,
                old_level=entry.progress.champ_level,
                new_level=result.progress.champ_level,
                progress=result.progress,
                is_lead=is_lead,
            ))
    return levelups
