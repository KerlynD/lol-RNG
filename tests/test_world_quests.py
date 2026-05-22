"""Tests for region quests (v3 Phase 4)."""
from __future__ import annotations

from bot.game.world.quests import (
    QUESTS,
    REGION_QUESTS,
    get_quest,
    quest_current,
    quests_for_region,
)
from bot.game.world.regions import WORLD


def test_every_region_has_quests():
    assert set(REGION_QUESTS) == set(WORLD)
    for region_key, quests in REGION_QUESTS.items():
        assert len(quests) >= 1
        for quest in quests:
            assert quest.region == region_key
            assert quest.key.startswith(f"{region_key}:")


def test_quests_index_is_consistent():
    flat = [q for quests in REGION_QUESTS.values() for q in quests]
    assert len(QUESTS) == len(flat)
    for quest in flat:
        assert get_quest(quest.key) is quest


def test_counter_key_only_for_progress_quests():
    for quest in QUESTS.values():
        ck = quest.counter_key()
        if quest.objective_kind in ("hunt", "wild"):
            assert ck and ck.startswith(quest.region)
        else:
            assert ck is None


def test_quest_current_counter_uses_baseline():
    quest = next(q for q in QUESTS.values() if q.objective_kind == "hunt")
    # 10 cumulative wins, quest accepted at baseline 4 => 6 progress.
    assert quest_current(
        quest, counter_value=10, baseline=4, user_level=1, user_gold=0
    ) == 6
    # Never negative.
    assert quest_current(
        quest, counter_value=2, baseline=5, user_level=1, user_gold=0
    ) == 0


def test_quests_for_region():
    assert quests_for_region("bandle_city")
    assert quests_for_region("nowhere") == ()


def test_rewards_scale_up_across_regions():
    bandle = max(q.reward_gold for q in quests_for_region("bandle_city"))
    targon = max(q.reward_gold for q in quests_for_region("targon"))
    assert targon > bandle
