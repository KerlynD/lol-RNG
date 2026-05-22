"""Ranked PvP ladder — LP economy, tiers, placements, streaks, decay.

Pure functions only. No Discord, no DB. All ladder math lives here and is
unit-tested in tests/test_ranked.py. The orchestration that reads/writes the
database is in bot/game/ranked_flow.py.
"""
from __future__ import annotations

from dataclasses import dataclass

# --- Rank tiers --------------------------------------------------------------
# (name, min_lp), ascending. A tier's index is its position in this tuple and
# is what the cross-rank Elo factor compares.

RANK_TIERS: tuple[tuple[str, int], ...] = (
    ("Iron", 0),
    ("Bronze", 200),
    ("Silver", 400),
    ("Gold", 600),
    ("Platinum", 800),
    ("Diamond", 1000),
    ("Master", 1200),
    ("Grandmaster", 1400),
    ("Challenger", 1600),
)

PLACEMENT_GAMES = 5

# --- LP economy (same-tier) --------------------------------------------------
# Base gain and loss are equal so a flat 50% win rate keeps a player still.
BASE_LP = 15
WIN_STREAK_THRESHOLD = 3
LOSS_STREAK_THRESHOLD = 3
WIN_GAIN_CAP = 25       # most LP a single win can grant
WIN_GAIN_FLOOR = 10     # least LP a win can grant (suppressed by a loss streak)
LOSS_MAG_CAP = 25       # most LP a single loss can cost
LOSS_MAG_FLOOR = 10     # least LP a loss can cost (protected by a win streak)

# --- Cross-rank Elo factor ---------------------------------------------------
# Fixed exchanges that OVERRIDE streak scaling whenever the two players are in
# different tiers. Sign convention: win values positive, loss values negative.
PUNCH_UP_WIN = 25       # lower-ranked player beats a higher-ranked one
PUNCH_UP_LOSS = -5      # lower-ranked player loses to a higher-ranked one
PUNCH_DOWN_WIN = 5      # higher-ranked player beats a lower-ranked one
PUNCH_DOWN_LOSS = -25   # higher-ranked player loses to a lower-ranked one
LOCKOUT_WIN = 0         # attacking 2+ tiers down — winning earns nothing
LOCKOUT_LOSS = -25      # ...but losing still costs the maximum

# --- Decay -------------------------------------------------------------------
DECAY_LP = 15
DECAY_MIN_TIER_LP = 800     # Platinum and above are subject to decay
DECAY_FLOOR_LP = 600        # decay never pushes a player below Gold
DECAY_INACTIVITY_DAYS = 3   # days without initiating a ranked match

# --- Placement / season ------------------------------------------------------
PLACEMENT_BASE_LP = 100
PLACEMENT_WIN_LP = 35
PLACEMENT_LOSS_LP = 15
SEASON_CARRY_CAP = 150      # max placement head start from prior-season MMR


def tier_index(lp: int) -> int:
    """Index into RANK_TIERS for the given LP."""
    idx = 0
    for i, (_name, floor) in enumerate(RANK_TIERS):
        if lp >= floor:
            idx = i
    return idx


def tier_name(lp: int) -> str:
    return RANK_TIERS[tier_index(lp)][0]


def next_tier_floor(lp: int) -> int | None:
    """LP threshold of the next tier up, or None if already at Challenger."""
    idx = tier_index(lp)
    if idx >= len(RANK_TIERS) - 1:
        return None
    return RANK_TIERS[idx + 1][1]


@dataclass(frozen=True)
class StreakValues:
    win_gain: int       # LP this player gets for a win (positive)
    loss_amount: int    # LP this player gets for a loss (negative)


def streak_adjusted_values(win_streak: int, loss_streak: int) -> StreakValues:
    """Per-player same-tier LP values after applying streak scaling.

    A 3+ win streak raises the win gain (+2 per step, cap +25) and softens the
    loss (-1 per step, floor -10). A 3+ loss streak does the inverse. A player
    has at most one active streak; the other counter is 0.
    """
    win_gain = BASE_LP
    loss_amount = -BASE_LP

    if win_streak >= WIN_STREAK_THRESHOLD:
        steps = win_streak - (WIN_STREAK_THRESHOLD - 1)   # streak 3 -> 1 step
        win_gain = min(WIN_GAIN_CAP, BASE_LP + 2 * steps)
        loss_amount = -max(LOSS_MAG_FLOOR, BASE_LP - steps)
    elif loss_streak >= LOSS_STREAK_THRESHOLD:
        steps = loss_streak - (LOSS_STREAK_THRESHOLD - 1)
        loss_amount = -min(LOSS_MAG_CAP, BASE_LP + 2 * steps)
        win_gain = max(WIN_GAIN_FLOOR, BASE_LP - steps)

    return StreakValues(win_gain=win_gain, loss_amount=loss_amount)


@dataclass(frozen=True)
class LpExchange:
    attacker_delta: int
    defender_delta: int


def lp_exchange(
    attacker_tier_idx: int,
    defender_tier_idx: int,
    attacker_won: bool,
    *,
    attacker_win_streak: int = 0,
    attacker_loss_streak: int = 0,
    defender_win_streak: int = 0,
    defender_loss_streak: int = 0,
) -> LpExchange:
    """LP change for both players from one ranked match.

    Same-tier matches use streak-scaled exchanges. Any cross-rank match uses
    the fixed Elo numbers and ignores streak scaling — the Elo factor wins.
    """
    gap = attacker_tier_idx - defender_tier_idx

    if gap == 0:
        atk = streak_adjusted_values(attacker_win_streak, attacker_loss_streak)
        dfn = streak_adjusted_values(defender_win_streak, defender_loss_streak)
        if attacker_won:
            return LpExchange(atk.win_gain, dfn.loss_amount)
        return LpExchange(atk.loss_amount, dfn.win_gain)

    if gap < 0:        # attacker is the lower-ranked player — punching up
        atk_win, atk_loss = PUNCH_UP_WIN, PUNCH_UP_LOSS
        dfn_win, dfn_loss = PUNCH_DOWN_WIN, PUNCH_DOWN_LOSS
    elif gap == 1:     # attacker exactly one tier above — mild punch down
        atk_win, atk_loss = PUNCH_DOWN_WIN, PUNCH_DOWN_LOSS
        dfn_win, dfn_loss = PUNCH_UP_WIN, PUNCH_UP_LOSS
    else:              # gap >= 2 — anti-farm lockout
        atk_win, atk_loss = LOCKOUT_WIN, LOCKOUT_LOSS
        dfn_win, dfn_loss = PUNCH_UP_WIN, PUNCH_UP_LOSS

    if attacker_won:
        return LpExchange(atk_win, dfn_loss)
    return LpExchange(atk_loss, dfn_win)


def placement_starting_lp(wins: int, losses: int, mmr_carry: int = 0) -> int:
    """LP a player is seeded with after finishing their 5 placement games."""
    lp = (
        PLACEMENT_BASE_LP
        + PLACEMENT_WIN_LP * wins
        - PLACEMENT_LOSS_LP * losses
        + mmr_carry
    )
    return max(0, lp)


def season_mmr_carry(hidden_mmr: int) -> int:
    """Soft placement head start derived from a prior season's hidden MMR."""
    return min(SEASON_CARRY_CAP, max(0, round((hidden_mmr - PLACEMENT_BASE_LP) * 0.10)))


def is_decay_eligible(lp: int) -> bool:
    """Players in Platinum or above are subject to inactivity decay."""
    return lp >= DECAY_MIN_TIER_LP


def apply_decay(lp: int) -> int:
    """One tick of inactivity decay — never drops a player below Gold."""
    return max(DECAY_FLOOR_LP, lp - DECAY_LP)
