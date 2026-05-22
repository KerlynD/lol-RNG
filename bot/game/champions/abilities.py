"""Champion abilities — Q/W/E/R ranks and the win-% bonus they grant.

Pure functions. Q/W/E cap at rank 5, R caps at rank 3 and is level-gated like
real League (rank 1 at champ level 6, rank 2 at 11, rank 3 at 16). 18 champ
levels yield exactly 18 ability points -> a fully maxed Q5 W5 E5 R3.
"""
from __future__ import annotations

from dataclasses import replace

from bot.db.queries import ChampProgress

ABILITIES: tuple[str, ...] = ("q", "w", "e", "r")
QWE_MAX_RANK = 5
R_MAX_RANK = 3
R_LEVEL_GATES: dict[int, int] = {1: 6, 2: 11, 3: 16}  # next_r_rank -> champ level

# Win-% granted per ability rank. R is worth more than a normal rank.
QWE_RANK_BONUS = 0.6
R_RANK_BONUS = 1.4


def ability_win_bonus(q: int, w: int, e: int, r: int) -> float:
    """Total win-% bonus from a champion's ability ranks. Maxed = 13.2%."""
    return (q + w + e) * QWE_RANK_BONUS + r * R_RANK_BONUS


def progress_win_bonus(progress: ChampProgress) -> float:
    return ability_win_bonus(
        progress.q_rank, progress.w_rank, progress.e_rank, progress.r_rank
    )


def _rank_of(progress: ChampProgress, ability: str) -> int:
    return getattr(progress, f"{ability}_rank")


def can_rank(ability: str, progress: ChampProgress) -> bool:
    """Whether the player may spend a point on this ability right now."""
    ability = ability.lower()
    if ability not in ABILITIES or progress.unspent_points <= 0:
        return False
    if ability == "r":
        if progress.r_rank >= R_MAX_RANK:
            return False
        return progress.champ_level >= R_LEVEL_GATES[progress.r_rank + 1]
    return _rank_of(progress, ability) < QWE_MAX_RANK


def apply_rank(progress: ChampProgress, ability: str) -> ChampProgress:
    """Pure rank-up (used in tests + previews). The DB performs the real
    atomic update in queries.rank_ability."""
    ability = ability.lower()
    field = f"{ability}_rank"
    return replace(
        progress,
        **{field: _rank_of(progress, ability) + 1},
        unspent_points=progress.unspent_points - 1,
    )
