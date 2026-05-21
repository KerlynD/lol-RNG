"""Economy constants and scaling formulas (PRD §3, §8, §9).

All payouts are pure functions — easy to unit-test and tune in one place.
"""
from __future__ import annotations

# --- Rolling costs (flat by level per PRD §8.2) ------------------------------
BASE_ROLL_COST = 500

ROLL_COSTS: dict[int, int] = {
    1: BASE_ROLL_COST,        # /roll
    10: BASE_ROLL_COST * 10,  # /roll10
    100: BASE_ROLL_COST * 100,  # /roll100
    1000: BASE_ROLL_COST * 1000,  # /roll1000
}


# --- Fragment redemption thresholds (PRD §8.3) -------------------------------
# No T7 entry — Death tier has no fragment path.
FRAGMENT_THRESHOLDS: dict[int, int] = {
    1: 10,
    2: 15,
    3: 25,
    4: 40,
    5: 75,
    6: 150,
}


def fragment_item_key(tier: int) -> str:
    return f"fragment_t{tier}"


# --- Trading -----------------------------------------------------------------
TRADE_TAX_GOLD = 500


# --- Gold scaling (PRD §3 tiered scaling) ------------------------------------
#
# Per-level multiplier: a level grows base payout by ~15%/level, capping at 5x at L30.
# Prestige adds a flat +5% per stack on top.

GOLD_LEVEL_GROWTH_PER_LEVEL = 0.15
GOLD_LEVEL_CAP_MULT = 5.0
PRESTIGE_GOLD_BONUS_PER_STACK = 0.05


def gold_payout(base: int, user_level: int, prestige: int = 0) -> int:
    """Scale a base gold value by user's level and prestige stacks."""
    if base <= 0:
        return 0
    level_mult = min(
        GOLD_LEVEL_CAP_MULT,
        1.0 + GOLD_LEVEL_GROWTH_PER_LEVEL * max(0, user_level - 1),
    )
    prestige_mult = 1.0 + PRESTIGE_GOLD_BONUS_PER_STACK * max(0, prestige)
    return int(round(base * level_mult * prestige_mult))
