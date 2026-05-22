"""Tests for the Runeterra world map + region-locked rolls (v3 Phase 1)."""
from __future__ import annotations

import random

from bot.game.rolling import pick_tier
from bot.game.world.regions import (
    MAX_CHAMPION_TIER,
    REGION_ORDER,
    STARTING_REGION,
    WORLD,
    region_distance,
    roll_tier_cap,
)


def test_every_region_in_order_list():
    assert set(REGION_ORDER) == set(WORLD)


def test_travel_graph_is_symmetric():
    for key, region in WORLD.items():
        for nb in region.neighbors:
            assert nb in WORLD
            assert key in WORLD[nb].neighbors


def test_all_regions_reachable_from_start():
    for key in WORLD:
        assert region_distance(STARTING_REGION, key) >= 0, key


def test_bandle_city_only_leads_to_demacia():
    assert WORLD[STARTING_REGION].neighbors == ("demacia",)


def test_region_distance_basics():
    assert region_distance("bandle_city", "bandle_city") == 0
    assert region_distance("bandle_city", "demacia") == 1
    assert region_distance("demacia", "freljord") == 1
    assert region_distance("bandle_city", "nowhere") == -1


def test_roll_tier_cap_per_region():
    assert roll_tier_cap("bandle_city") == 2
    assert roll_tier_cap("demacia") == 3
    assert roll_tier_cap("freljord") == 4
    assert roll_tier_cap("ionia") == 5
    # Lore-rated above T7 still clamps to the champion ceiling.
    assert roll_tier_cap("targon") == MAX_CHAMPION_TIER
    assert roll_tier_cap("noxus") == MAX_CHAMPION_TIER


def test_roll_tier_cap_unknown_region_is_uncapped():
    assert roll_tier_cap(None) == MAX_CHAMPION_TIER
    assert roll_tier_cap("atlantis") == MAX_CHAMPION_TIER


def test_pick_tier_respects_max_tier():
    rng = random.Random(42)
    for _ in range(500):
        tier = pick_tier(1, rng=rng, max_tier=2)
        assert tier <= 2


def test_pick_tier_clamps_when_guarantee_exceeds_cap():
    # /roll1000 guarantees >= T4, but a T2-capped region clamps it to T2.
    rng = random.Random(7)
    for _ in range(100):
        assert pick_tier(1000, rng=rng, max_tier=2) == 2


def test_pick_tier_uncapped_can_exceed_cap_value():
    rng = random.Random(1)
    seen = {pick_tier(1, rng=rng) for _ in range(2000)}
    assert max(seen) >= 3  # without a cap, higher tiers do appear
