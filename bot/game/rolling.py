"""Rolling logic: tier-weighted champion selection + multiplier odds shifts.

Pure functions on top of bot.db.queries. No Discord deps.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from bot.db.queries import Champion

# --- Tier weights ------------------------------------------------------------
#
# Base /roll uses pretty steep odds for high tiers; multipliers shift the
# distribution toward higher tiers AND enforce a guaranteed minimum tier
# (PRD §8.1). Tier 7 (Death) is intentionally negligible at all multipliers —
# you don't 1000x-roll your way into Kindred; only true 1x rolls or fragments
# can land Death tier. Wait — PRD §8.3 says Death has no fragment path. So
# Death only drops from true rolls at the seed_weights probability. We keep
# Tier 7 at trace probability across multipliers and let `seed_weights`-driven
# /roll luck handle it.

# Each row is a (multiplier -> dict[tier -> weight]).
TIER_WEIGHTS_BY_MULTIPLIER: dict[int, dict[int, float]] = {
    1: {
        1: 0.55,
        2: 0.30,
        3: 0.12,
        4: 0.025,
        5: 0.0045,
        6: 0.0005,
        7: 0.00001,  # ~1 in 100k from a single /roll — base rarity
    },
    10: {
        1: 0.35,
        2: 0.40,
        3: 0.20,
        4: 0.04,
        5: 0.009,
        6: 0.001,
        7: 0.00001,
    },
    100: {
        1: 0.0,   # guaranteed >= Tier 2 (PRD §8.1: 10x guarantees ≥ T2; 100x ≥ T3)
        2: 0.0,
        3: 0.55,
        4: 0.35,
        5: 0.08,
        6: 0.015,
        7: 0.00005,
    },
    1000: {
        1: 0.0,
        2: 0.0,
        3: 0.0,
        4: 0.55,  # guaranteed ≥ Tier 4
        5: 0.35,
        6: 0.09,
        7: 0.0001,  # 10x Death rate compared to base — still extremely rare
    },
}

VALID_MULTIPLIERS = tuple(TIER_WEIGHTS_BY_MULTIPLIER.keys())


# --- Prestige Death-tier boost (PRD §11) -------------------------------------
# After first prestige, base Death rate doubles (1/1M → 1/500K equivalent).
# Implemented as a multiplicative boost to the tier-7 weight.
PRESTIGE_DEATH_MULTIPLIER = 2.0


@dataclass(frozen=True)
class RollResult:
    champion: Champion
    multiplier: int
    tier: int


def _apply_prestige_to_weights(
    weights: dict[int, float], prestige: int
) -> dict[int, float]:
    if prestige <= 0 or 7 not in weights or weights[7] <= 0:
        return weights
    boosted = dict(weights)
    boosted[7] = weights[7] * (PRESTIGE_DEATH_MULTIPLIER ** prestige)
    return boosted


def pick_tier(
    multiplier: int,
    prestige: int = 0,
    rng: random.Random | None = None,
) -> int:
    if multiplier not in TIER_WEIGHTS_BY_MULTIPLIER:
        raise ValueError(f"Unsupported multiplier {multiplier}; expected {VALID_MULTIPLIERS}")
    rng = rng or random
    weights = _apply_prestige_to_weights(TIER_WEIGHTS_BY_MULTIPLIER[multiplier], prestige)
    tiers = list(weights.keys())
    probs = [weights[t] for t in tiers]
    total = sum(probs)
    if total <= 0:
        raise RuntimeError("All tier weights zero — bad config.")
    return rng.choices(tiers, weights=probs, k=1)[0]


def pick_champion_in_tier(
    champions: list[Champion],
    rng: random.Random | None = None,
) -> Champion:
    """Weighted pick by champion.drop_weight."""
    if not champions:
        raise ValueError("Empty tier — cannot pick a champion.")
    rng = rng or random
    weights = [c.drop_weight for c in champions]
    return rng.choices(champions, weights=weights, k=1)[0]


def roll_champion(
    multiplier: int,
    champions_by_tier: dict[int, list[Champion]],
    prestige: int = 0,
    rng: random.Random | None = None,
) -> RollResult:
    """End-to-end roll: pick a tier, then pick a champion within that tier.

    Falls back to next-lower tier if the chosen tier has no champions seeded
    (defensive — should never happen with the full roster).
    """
    rng = rng or random
    tier = pick_tier(multiplier, prestige=prestige, rng=rng)
    # Fallback in case a tier is empty:
    pool_tiers = sorted((t for t, c in champions_by_tier.items() if c), reverse=True)
    if tier not in champions_by_tier or not champions_by_tier[tier]:
        candidates = [t for t in pool_tiers if t <= tier]
        if not candidates:
            raise RuntimeError("No champions available to roll.")
        tier = candidates[0]
    champ = pick_champion_in_tier(champions_by_tier[tier], rng=rng)
    return RollResult(champion=champ, multiplier=multiplier, tier=tier)


# --- Pull resolution: ownership + dupe → fragment + reap divert --------------


@dataclass(frozen=True)
class PullResolution:
    champion: Champion
    was_dupe: bool
    fragment_awarded_tier: int | None   # which fragment, if any
    reap_diverted_to: int | None        # caster_id, if pull was reaped
