"""Tests for the encounter pool and weighting."""
import random
from collections import Counter

from bot.game.pve.camps import CAMPS, ENCOUNTER_POOL, cooldown_seconds, roll_encounter


def test_every_pool_key_is_valid():
    for keys, _ in ENCOUNTER_POOL:
        for k in keys:
            assert k in CAMPS, f"{k} in pool but not in CAMPS"


def test_pool_weights_positive():
    for _, w in ENCOUNTER_POOL:
        assert w > 0


def test_encounter_distribution_roughly_matches_weights():
    """Small camps should heavily dominate the pool; drakes should be rare."""
    rng = random.Random(123)
    counts: Counter[str] = Counter()
    for _ in range(50_000):
        camp = roll_encounter(rng=rng)
        counts[camp.key] += 1

    # Wolves & Raptors are biggest buckets (weight 22 each)
    big = counts["wolves"] + counts["raptors"]
    # Drake encounters total weight is 1, spread across 6 drakes
    drakes = sum(counts[k] for k in counts if k.startswith("drake_"))
    assert big > drakes * 30   # wolves+raptors should crush drakes

    # Each specific drake should at least show up a few times in 50k trials
    drake_keys = [k for k in CAMPS if k.startswith("drake_")]
    assert all(counts[k] > 0 for k in drake_keys)


def test_cooldown_seconds_within_range():
    rng = random.Random(7)
    for camp in CAMPS.values():
        low, high = camp.cooldown_range
        for _ in range(20):
            cd = cooldown_seconds(camp, rng=rng)
            assert low <= cd <= high
