"""Tests for the Void easter-egg hint helpers (pure functions)."""
from __future__ import annotations

from bot.game.world.goals import REGION_UNLOCK_GOALS
from bot.game.world.void_hints import (
    HUNT_WHISPERS,
    LOUD_HINT,
    STATIC_HINT,
    pick_hint,
    void_proximity,
)


def test_void_proximity_uses_minimum_pillar():
    # Gold maxed but level 1, hunts 0 -> floored at 0 by the slowest pillar.
    assert void_proximity(200_000, 1, 0) == 0.0


def test_void_proximity_full_when_all_three_met():
    assert void_proximity(200_000, 27, 40) == 1.0


def test_void_proximity_picks_min_of_normalized():
    # Gold 50% / level 100% / hunts 100% -> the min is the gold pillar.
    assert void_proximity(100_000, 27, 40) == 0.5


def test_void_proximity_can_exceed_one():
    # No clamp — overshooting one pillar doesn't matter, the others still cap.
    assert void_proximity(500_000, 30, 50) > 1.0


def test_pick_hint_static_below_loud_threshold():
    assert pick_hint("shurima", 0.0) == STATIC_HINT["shurima"]
    assert pick_hint("shurima", 0.79) == STATIC_HINT["shurima"]
    assert pick_hint("targon", 0.5) == STATIC_HINT["targon"]


def test_pick_hint_loud_at_or_above_threshold():
    assert pick_hint("shurima", 0.80) == LOUD_HINT["shurima"]
    assert pick_hint("targon", 0.80) == LOUD_HINT["targon"]
    assert pick_hint("shurima", 1.5) == LOUD_HINT["shurima"]


def test_pick_hint_silent_for_other_regions():
    for region in ("bandle_city", "demacia", "freljord", "ionia", "noxus",
                   "piltover_zaun", "bilgewater", "shadow_isles", "ixtal",
                   "void", "", "atlantis"):
        assert pick_hint(region, 1.0) is None


def test_hunt_whispers_only_for_shurima_and_targon():
    assert set(HUNT_WHISPERS) == {"shurima", "targon"}
    for whispers in HUNT_WHISPERS.values():
        assert len(whispers) >= 4
        # Every whisper is italicized flavor (wrapped in *...*).
        for line in whispers:
            assert line.startswith("*") and line.endswith("*")


def test_void_proximity_mirrors_real_unlock_goals():
    """Targets in void_hints stay synced with REGION_UNLOCK_GOALS["void"]."""
    goals = REGION_UNLOCK_GOALS["void"]
    targets = {g.kind: g.target for g in goals}
    # Hitting the exact thresholds should yield proximity == 1.0.
    assert void_proximity(targets["gold"], targets["level"], targets["count"]) == 1.0
