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


# Cross-tier fragment conversion (v3):
#   same tier:   cost = threshold[N]      (×1)
#   +1 tier up:  cost = threshold[N] × 2  (double for one tier up)
#   +2 tier up:  cost = threshold[N] × 3  (triple for two tiers up)
# Tier 7 (Death) has no fragment path. Region roll cap still applies.
MAX_FRAGMENT_REDEEM_TIER = 6
MAX_UPGRADE_STEPS = 2


def redeem_cost(source_tier: int, target_tier: int) -> int | None:
    """Fragments of `source_tier` needed to redeem a `target_tier` pull, or
    None if the combination isn't valid (wrong direction, too many steps,
    or beyond the T6 fragment ceiling)."""
    if source_tier not in FRAGMENT_THRESHOLDS:
        return None
    if target_tier > MAX_FRAGMENT_REDEEM_TIER:
        return None
    step = target_tier - source_tier
    if step < 0 or step > MAX_UPGRADE_STEPS:
        return None
    return FRAGMENT_THRESHOLDS[source_tier] * (step + 1)


def available_redeem_options(
    inventory: dict[str, int], region_tier_cap: int
) -> list[tuple[int, int, int]]:
    """Every redemption the user can afford right now, given their inventory
    and the region roll cap. Each tuple is (source_tier, target_tier, cost),
    sorted by target tier descending so the strongest pulls surface first."""
    cap = min(region_tier_cap, MAX_FRAGMENT_REDEEM_TIER)
    out: list[tuple[int, int, int]] = []
    for source in FRAGMENT_THRESHOLDS:
        held = inventory.get(fragment_item_key(source), 0)
        if held <= 0:
            continue
        for step in range(MAX_UPGRADE_STEPS + 1):
            target = source + step
            if target > cap:
                break
            cost = redeem_cost(source, target)
            if cost is not None and held >= cost:
                out.append((source, target, cost))
    out.sort(key=lambda row: (-row[1], row[0], row[2]))
    return out


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
