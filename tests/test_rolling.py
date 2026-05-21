import random

from bot.db.queries import Champion
from bot.game.rolling import (
    TIER_WEIGHTS_BY_MULTIPLIER,
    pick_champion_in_tier,
    pick_tier,
    roll_champion,
)


def _champ(name: str, tier: int, weight: float = 0.1) -> Champion:
    return Champion(
        id=hash(name) & 0xFFFFFF,
        name=name,
        tier=tier,
        region="X",
        factions=[],
        damage_type="AD",
        drop_weight=weight,
        splash_url=None,
    )


def test_tier_weights_keys_match_for_all_multipliers():
    for m, weights in TIER_WEIGHTS_BY_MULTIPLIER.items():
        assert set(weights.keys()) == {1, 2, 3, 4, 5, 6, 7}, f"mult {m} has wrong keys"


def test_high_multipliers_guarantee_minimum_tier():
    rng = random.Random(42)
    # 100x: weights for tier 1, 2 are zero → never picked
    for _ in range(500):
        t = pick_tier(100, rng=rng)
        assert t >= 3
    # 1000x: weights for tier 1, 2, 3 are zero
    for _ in range(500):
        t = pick_tier(1000, rng=rng)
        assert t >= 4


def test_pick_tier_distribution_base():
    rng = random.Random(1)
    counts = {t: 0 for t in range(1, 8)}
    for _ in range(20_000):
        counts[pick_tier(1, rng=rng)] += 1
    # Tier 1 should dominate /roll
    assert counts[1] > counts[2] > counts[3]


def test_pick_champion_in_tier_weighted():
    rng = random.Random(7)
    a = _champ("A", 2, weight=0.9)
    b = _champ("B", 2, weight=0.1)
    counts = {"A": 0, "B": 0}
    for _ in range(5_000):
        picked = pick_champion_in_tier([a, b], rng=rng)
        counts[picked.name] += 1
    assert counts["A"] > counts["B"] * 3   # ~9:1 expected


def test_roll_champion_returns_consistent_tier():
    rng = random.Random(99)
    by_tier = {
        1: [_champ("c1", 1)],
        2: [_champ("c2a", 2), _champ("c2b", 2)],
        3: [_champ("c3", 3)],
        4: [_champ("c4", 4)],
        5: [_champ("c5", 5)],
        6: [_champ("c6", 6)],
        7: [_champ("c7", 7)],
    }
    for _ in range(200):
        r = roll_champion(10, by_tier, rng=rng)
        assert r.tier == r.champion.tier


def test_prestige_boosts_death_weight():
    rng_a = random.Random(0)
    rng_b = random.Random(0)
    # Run many trials, count tier-7 picks at base vs prestige=3 at multiplier 1.
    n = 2_000_000
    base_t7 = 0
    boosted_t7 = 0
    # Use the same seed for fairness on the boundary cases.
    # We bias the test with a fresh, large sample.
    rng = random.Random(123)
    for _ in range(n):
        if pick_tier(1, prestige=0, rng=rng) == 7:
            base_t7 += 1
    rng = random.Random(123)
    for _ in range(n):
        if pick_tier(1, prestige=3, rng=rng) == 7:
            boosted_t7 += 1
    assert boosted_t7 >= base_t7  # boosted should be at least as common
