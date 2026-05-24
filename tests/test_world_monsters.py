"""Tests for region-scoped monster pools + backtracking decay (v3 Phase 2)."""
from __future__ import annotations

import random
from dataclasses import dataclass

from bot.game.world.monsters import (
    REGION_POOLS,
    roll_region_encounter,
    wild_champ_chance,
    wild_champion_camp,
)
from bot.game.world.regions import WORLD, reward_decay_factor


def test_every_region_has_a_monster_pool():
    assert set(REGION_POOLS) == set(WORLD)


def test_camps_stay_within_region_tier_band():
    for region_key, (_chance, camps) in REGION_POOLS.items():
        region = WORLD[region_key]
        for spec, weight in camps:
            assert weight > 0
            # Monsters may sit one tier under/over the band; champs cap at 7
            # so the deepest regions floor their content there.
            assert 1 <= spec.tier <= region.tier_max + 1, (
                f"{spec.name} tier {spec.tier} outside {region_key} band"
            )


def test_wild_champ_chance_is_a_probability():
    for region_key in REGION_POOLS:
        assert 0.0 <= wild_champ_chance(region_key) <= 1.0
    assert wild_champ_chance("nowhere") == 0.0


def test_roll_region_encounter_returns_a_region_camp():
    rng = random.Random(3)
    for _ in range(200):
        camp = roll_region_encounter("bandle_city", rng=rng)
        assert camp is not None
        assert camp.key.startswith("bandle_city:")
    assert roll_region_encounter("nowhere") is None


@dataclass
class _Champ:
    id: int
    name: str
    tier: int
    splash_url: str | None = None


def test_wild_champion_camp_payout_beats_a_monster():
    camp = wild_champion_camp(_Champ(id=1, name="Teemo", tier=2))
    assert camp.name == "Teemo"
    assert camp.tier == 2
    # Champions pay more than the tier*70 monster baseline.
    assert camp.base_gold > 2 * 70


def test_wild_champion_camp_tier_override_scales_to_region():
    """A roster-T2 champion encountered in Bilgewater (T5-T6) fights as T6."""
    miss_fortune = _Champ(id=42, name="Miss Fortune", tier=2)
    camp = wild_champion_camp(miss_fortune, tier=6)
    assert camp.name == "Miss Fortune"   # identity preserved
    assert camp.tier == 6                # but danger = region tier
    # Payout and fragment drop scale with the encounter tier, not roster tier.
    assert camp.base_gold == 6 * 150
    assert ("fragment_t6", 0.15) in camp.drops


def test_reward_decay_at_frontier_is_full():
    # Only Bandle City unlocked, standing in Bandle City — no decay.
    assert reward_decay_factor("bandle_city", ["bandle_city"]) == 1.0


def test_reward_decay_punishes_backtracking():
    # Unlocked up to Freljord, but hunting back in Bandle City.
    unlocked = ["bandle_city", "demacia", "freljord"]
    factor = reward_decay_factor("bandle_city", unlocked)
    assert factor < 1.0
    assert factor >= 0.10


def test_reward_decay_floor():
    unlocked = list(WORLD.keys())  # everything unlocked
    factor = reward_decay_factor("bandle_city", unlocked)
    assert factor == 0.10
