"""Leveling: XP curve, level unlocks, and apply_xp helper (PRD §3)."""
from __future__ import annotations

from dataclasses import dataclass

LEVEL_CAP = 30
MAX_LOADOUT_SLOTS = 5


@dataclass(frozen=True)
class LevelUnlocks:
    loadout_slots: int
    max_action_tier: int
    synergy_active: bool
    can_prestige: bool


# Per-level unlocks. Levels not listed inherit from the previous entry.
_UNLOCK_MILESTONES: dict[int, LevelUnlocks] = {
    1:  LevelUnlocks(loadout_slots=3, max_action_tier=2, synergy_active=False, can_prestige=False),
    5:  LevelUnlocks(loadout_slots=3, max_action_tier=3, synergy_active=False, can_prestige=False),
    10: LevelUnlocks(loadout_slots=4, max_action_tier=4, synergy_active=True,  can_prestige=False),
    15: LevelUnlocks(loadout_slots=4, max_action_tier=5, synergy_active=True,  can_prestige=False),
    20: LevelUnlocks(loadout_slots=5, max_action_tier=6, synergy_active=True,  can_prestige=False),
    25: LevelUnlocks(loadout_slots=5, max_action_tier=7, synergy_active=True,  can_prestige=False),
    30: LevelUnlocks(loadout_slots=5, max_action_tier=7, synergy_active=True,  can_prestige=True),
}


def unlocks_for(level: int) -> LevelUnlocks:
    """Resolve the unlocks that are active at `level` (highest milestone <= level)."""
    best = _UNLOCK_MILESTONES[1]
    for milestone, unlocks in _UNLOCK_MILESTONES.items():
        if milestone <= level:
            best = unlocks
    return best


# --- XP curve ----------------------------------------------------------------
#
# Moderate grind. xp_to_next_level(L) is the XP needed to go from L → L+1.
# Total XP to reach level 30 ≈ 80,000.

_BASE_XP = 100


def xp_to_next_level(level: int) -> int:
    if level >= LEVEL_CAP:
        return 0
    # Quadratic-ish growth: easy early levels, real climb later.
    return _BASE_XP + level * level * 8


def total_xp_to_reach(level: int) -> int:
    total = 0
    for L in range(1, level):
        total += xp_to_next_level(L)
    return total


@dataclass(frozen=True)
class XpResult:
    new_xp: int
    new_level: int
    leveled_up_to: int | None  # None if no level-up happened


def apply_xp(current_xp: int, current_level: int, delta: int) -> XpResult:
    """Apply XP gain and roll over levels. Caps at LEVEL_CAP."""
    if delta <= 0 or current_level >= LEVEL_CAP:
        return XpResult(new_xp=current_xp, new_level=current_level, leveled_up_to=None)

    xp = current_xp + delta
    level = current_level
    leveled_to: int | None = None

    while level < LEVEL_CAP:
        needed = xp_to_next_level(level)
        if xp < needed:
            break
        xp -= needed
        level += 1
        leveled_to = level

    if level >= LEVEL_CAP:
        # At cap, freeze XP at 0 (nothing more to earn toward next level).
        xp = 0

    return XpResult(new_xp=xp, new_level=level, leveled_up_to=leveled_to)
