"""Champion leveling — per-owned-champion XP curve and level rollover.

Pure functions. Champions level 1->18; higher-tier champions need much more
XP per level. Each level-up grants one ability point (see abilities.py).
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from bot.db.queries import ChampProgress

CHAMP_LEVEL_CAP = 18
_CHAMP_BASE_XP = 60

# Champ-XP amounts per source (owner: hunt + world boss highest, rest menial).
HUNT_LEAD_FACTOR = 1.5        # /hunt-camp lead champ: camp.base_xp * this
WORLDBOSS_STRIKE_XP = 150     # flat per /strike, to the striking lead champ
EXPLORE_LEAD_FACTOR = 0.35    # /explore combat lead: mob.base_xp * this
AMBIENT_WIN_XP = 40           # flat, ambient encounter win
HUNT_PASSIVE_SHARE = 0.15     # non-lead alive loadout champ share (hunt / boss)
EXPLORE_PASSIVE_SHARE = 0.10  # ...for explore / ambient


def champ_xp_to_next(champ_level: int, tier: int) -> int:
    """XP needed to go from `champ_level` to the next. 0 at the cap.

    Tier scales the whole curve: a Tier-7 champ needs ~3.1x the XP of a
    Tier-1 at every level."""
    if champ_level >= CHAMP_LEVEL_CAP:
        return 0
    tier_mult = 1.0 + 0.35 * (tier - 1)
    return int((_CHAMP_BASE_XP + champ_level * champ_level * 14) * tier_mult)


def champ_total_xp_to_reach(level: int, tier: int) -> int:
    return sum(champ_xp_to_next(lvl, tier) for lvl in range(1, level))


@dataclass(frozen=True)
class ChampXpResult:
    progress: ChampProgress
    levels_gained: int


def apply_champ_xp(progress: ChampProgress, tier: int, delta: int) -> ChampXpResult:
    """Add champ XP, rolling over levels. Each level grants 1 ability point.
    Returns the new progress and how many levels were gained."""
    if delta <= 0 or progress.champ_level >= CHAMP_LEVEL_CAP:
        return ChampXpResult(progress=progress, levels_gained=0)

    xp = progress.champ_xp + delta
    level = progress.champ_level
    gained = 0
    while level < CHAMP_LEVEL_CAP:
        needed = champ_xp_to_next(level, tier)
        if xp < needed:
            break
        xp -= needed
        level += 1
        gained += 1

    if level >= CHAMP_LEVEL_CAP:
        xp = 0

    new_progress = replace(
        progress,
        champ_level=level,
        champ_xp=xp,
        unspent_points=progress.unspent_points + gained,
    )
    return ChampXpResult(progress=new_progress, levels_gained=gained)


def passive_xp(lead_xp: int, share: float = HUNT_PASSIVE_SHARE) -> int:
    """Champ XP a non-lead alive loadout member earns from the same fight."""
    return max(1, round(lead_xp * share))
