"""Tests for region unlock goals + travel costs (v3 Phase 3)."""
from __future__ import annotations

from bot.game.world.goals import (
    REGION_UNLOCK_GOALS,
    all_goals_met,
    evaluate_goals,
)
from bot.game.world.regions import WORLD, travel_cooldown_minutes, travel_cost


def test_every_region_except_start_has_unlock_goals():
    expected = set(WORLD) - {"bandle_city"}
    assert set(REGION_UNLOCK_GOALS) == expected


def test_count_goals_reference_real_regions():
    for goals in REGION_UNLOCK_GOALS.values():
        for goal in goals:
            if goal.kind == "count":
                assert goal.counter_key
                region_prefix = goal.counter_key.split(":")[0]
                assert region_prefix in WORLD


def test_each_region_has_gold_level_and_count_goal():
    for region_key, goals in REGION_UNLOCK_GOALS.items():
        kinds = {g.kind for g in goals}
        assert kinds == {"gold", "level", "count"}, region_key


def test_evaluate_goals_marks_done_correctly():
    # Demacia: 5,000 gold / level 3 / 1 wild kill in bandle_city.
    statuses = evaluate_goals("demacia", 5_000, 3, {"bandle_city:wild_kills": 1})
    assert all(s.done for s in statuses)


def test_evaluate_goals_marks_incomplete():
    statuses = evaluate_goals("demacia", 100, 1, {})
    assert not any(s.done for s in statuses)


def test_all_goals_met():
    assert all_goals_met("demacia", 5_000, 5, {"bandle_city:wild_kills": 3})
    assert not all_goals_met("demacia", 4_999, 5, {"bandle_city:wild_kills": 3})
    # No goals defined => open.
    assert all_goals_met("bandle_city", 0, 1, {})


def test_travel_cost_distance_dominates():
    # Shadow Isles -> Demacia (far) should cost much more than -> Ixtal (near).
    far = travel_cost("shadow_isles", "demacia")
    near = travel_cost("shadow_isles", "ixtal")
    assert far > near
    assert travel_cost("bandle_city", "bandle_city") == 0


def test_travel_cooldown_scales_with_distance():
    assert travel_cooldown_minutes("bandle_city", "demacia") >= 1
    assert (
        travel_cooldown_minutes("shadow_isles", "demacia")
        > travel_cooldown_minutes("bandle_city", "demacia")
    )
