"""Tests for folded region exploration (v3 Phase 5)."""
from __future__ import annotations

from bot.game.pve.encounters import REGIONS
from bot.game.world.explore import EXPLORE_REGION_MAP, explore_pool
from bot.game.world.regions import WORLD


def test_explore_map_covers_every_region():
    assert set(EXPLORE_REGION_MAP) == set(WORLD)


def test_explore_map_points_at_real_encounter_pools():
    for enc_keys in EXPLORE_REGION_MAP.values():
        for enc_key in enc_keys:
            assert enc_key in REGIONS, enc_key


def test_explore_pool_non_empty_for_every_region():
    for region_key in WORLD:
        assert explore_pool(region_key), region_key


def test_piltover_zaun_merges_two_pools():
    pool = explore_pool("piltover_zaun")
    assert len(pool) == len(REGIONS["Piltover"]) + len(REGIONS["Zaun"])
