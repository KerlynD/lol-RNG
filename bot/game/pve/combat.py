"""PVE combat resolver — punishing tier-diff curve (PRD v2)."""
from __future__ import annotations

import random
from dataclasses import dataclass

from bot.db.queries import Champion
from bot.game.combat import champion_stats, power_score
from bot.game.pve.camps import CampSpec

# Win probability by (champ_tier - camp_tier). Smoothed + symmetric around 50
# (a +N advantage mirrors the -N disadvantage) — the old table was steep and
# lopsided. Caps at 95 so weakness / red-buff / champ-level bonuses keep room.
PVE_WIN_PCT_BY_DIFF: dict[int, float] = {
    4: 95.0,
    3: 88.0,
    2: 78.0,
    1: 65.0,
    0: 50.0,
    -1: 35.0,
    -2: 22.0,
    -3: 12.0,
    -4: 5.0,
}

WEAKNESS_BONUS_PCT = 10.0   # +10% to base win % when damage type matches weakness

# Every camp has a small chance to drop a revive potion on a win.
REVIVE_POTION_DROP_CHANCE = 0.02

# Respawn duration scaled by tier deficit (more punishing for big mismatches).
RESPAWN_DURATION_SEC: dict[int, int] = {
    0:   5 * 60,
    -1:  8 * 60,
    -2: 12 * 60,
    -3: 15 * 60,
}
DEFAULT_RESPAWN_SEC = 15 * 60     # used when diff <= -4
FAIL_GOLD_PCT = 0.20              # lose 20% of camp.base_gold on loss


@dataclass(frozen=True)
class CampFightResult:
    won: bool
    win_pct: float                  # the % used for the roll (informative)
    gold_delta: int                 # +reward or −penalty
    drops: list[tuple[str, int]]    # only on win
    respawn_seconds: int             # 0 on win; positive on loss


def preview_win_pct(
    champ: Champion,
    camp: CampSpec,
    *,
    red_buff: bool = False,
    champ_bonus: float = 0.0,
) -> float:
    """The win % the player sees before deciding to engage.

    `champ_bonus` is the additive win-% from the champion's ability ranks
    (see bot/game/champions/abilities.py) — passed in as a plain float so this
    pure module never imports the progression layer. `red_buff` adds another
    flat +10%. The result is clamped to [1.0, 99.0] — never a sure thing.
    """
    diff = champ.tier - camp.tier
    diff = max(-4, min(4, diff))
    base = PVE_WIN_PCT_BY_DIFF[diff]
    if camp.weak_to and champ.damage_type == camp.weak_to:
        base += WEAKNESS_BONUS_PCT
    if red_buff:
        base += WEAKNESS_BONUS_PCT
    base += champ_bonus
    return max(1.0, min(99.0, base))


def resolve_camp_fight(
    champ: Champion,
    camp: CampSpec,
    *,
    red_buff: bool = False,
    champ_bonus: float = 0.0,
    rng: random.Random | None = None,
) -> CampFightResult:
    rng = rng or random
    win_pct = preview_win_pct(champ, camp, red_buff=red_buff, champ_bonus=champ_bonus)
    roll = rng.uniform(0.0, 100.0)
    won = roll < win_pct

    if won:
        drops: list[tuple[str, int]] = []
        for item_type, prob in camp.drops:
            if prob >= 1.0 or rng.random() < prob:
                drops.append((item_type, 1))
        if rng.random() < REVIVE_POTION_DROP_CHANCE:
            drops.append(("revive_potion", 1))
        return CampFightResult(
            won=True,
            win_pct=win_pct,
            gold_delta=camp.base_gold,
            drops=drops,
            respawn_seconds=0,
        )

    # Loss path
    diff = max(-4, min(4, champ.tier - camp.tier))
    respawn = RESPAWN_DURATION_SEC.get(diff, DEFAULT_RESPAWN_SEC)
    gold_loss = int(camp.base_gold * FAIL_GOLD_PCT)
    return CampFightResult(
        won=False,
        win_pct=win_pct,
        gold_delta=-gold_loss,
        drops=[],
        respawn_seconds=respawn,
    )


def lead_champion(loadout):
    """Return the highest-Power LoadoutEntry from the loadout, or None.

    Returns the entry (not a bare Champion) so the caller keeps `.progress`
    for the champion-level win bonus."""
    if not loadout:
        return None
    return max(loadout, key=lambda e: power_score(e.champion))
