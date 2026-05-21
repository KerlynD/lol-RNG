"""PVE combat resolver — punishing tier-diff curve (PRD v2)."""
from __future__ import annotations

import random
from dataclasses import dataclass

from bot.db.queries import Champion
from bot.game.combat import champion_stats, power_score
from bot.game.pve.camps import CampSpec

# Win probability by (champ_tier - camp_tier) — see PRD v2 plan.
PVE_WIN_PCT_BY_DIFF: dict[int, float] = {
    4: 99.0,
    3: 97.0,
    2: 90.0,
    1: 75.0,
    0: 50.0,
    -1: 15.0,
    -2: 2.0,
    -3: 0.5,
    -4: 0.5,
}

WEAKNESS_BONUS_PCT = 10.0   # +10% to base win % when damage type matches weakness

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
    champ: Champion, camp: CampSpec, *, red_buff: bool = False
) -> float:
    """The win % the player sees before deciding to engage.

    If `red_buff` is True (player holds a `red_buff` item), the win % bumps by
    another flat +10% (capped 99). The buff is only consumed on actual engage.
    """
    diff = champ.tier - camp.tier
    diff = max(-4, min(4, diff))
    base = PVE_WIN_PCT_BY_DIFF[diff]
    if camp.weak_to and champ.damage_type == camp.weak_to:
        base = min(99.0, base + WEAKNESS_BONUS_PCT)
    if red_buff:
        base = min(99.0, base + WEAKNESS_BONUS_PCT)
    return base


def resolve_camp_fight(
    champ: Champion,
    camp: CampSpec,
    *,
    red_buff: bool = False,
    rng: random.Random | None = None,
) -> CampFightResult:
    rng = rng or random
    win_pct = preview_win_pct(champ, camp, red_buff=red_buff)
    roll = rng.uniform(0.0, 100.0)
    won = roll < win_pct

    if won:
        drops: list[tuple[str, int]] = []
        for item_type, prob in camp.drops:
            if prob >= 1.0 or rng.random() < prob:
                drops.append((item_type, 1))
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


def lead_champion(loadout) -> Champion | None:
    """Return the highest-Power champ from the supplied loadout, or None."""
    if not loadout:
        return None
    return max((e.champion for e in loadout), key=power_score)
