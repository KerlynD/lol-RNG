"""Tests for the champion-XP curve + level rollover (bot/game/champions/leveling)."""
from __future__ import annotations

from bot.db.queries import ChampProgress
from bot.game.champions.leveling import (
    CHAMP_LEVEL_CAP,
    apply_champ_xp,
    champ_total_xp_to_reach,
    champ_xp_to_next,
    passive_xp,
)


def test_higher_tier_needs_more_xp_per_level():
    for level in range(1, CHAMP_LEVEL_CAP):
        assert champ_xp_to_next(level, 1) < champ_xp_to_next(level, 7)


def test_xp_to_next_grows_with_level():
    for tier in (1, 4, 7):
        for level in range(1, CHAMP_LEVEL_CAP - 1):
            assert champ_xp_to_next(level, tier) <= champ_xp_to_next(level + 1, tier)


def test_xp_to_next_is_zero_at_cap():
    assert champ_xp_to_next(CHAMP_LEVEL_CAP, 1) == 0
    assert champ_xp_to_next(CHAMP_LEVEL_CAP, 7) == 0


def test_one_level_then_partial():
    p = ChampProgress()  # level 1, xp 0, unspent_points 1
    needed_to_2 = champ_xp_to_next(1, tier=2)
    result = apply_champ_xp(p, tier=2, delta=needed_to_2 + 5)
    assert result.levels_gained == 1
    assert result.progress.champ_level == 2
    assert result.progress.champ_xp == 5
    assert result.progress.unspent_points == 2   # 1 starting + 1 gained


def test_multi_level_rollover():
    p = ChampProgress()
    huge = champ_total_xp_to_reach(5, tier=1)  # enough to span 1 -> 5
    result = apply_champ_xp(p, tier=1, delta=huge)
    assert result.progress.champ_level == 5
    assert result.levels_gained == 4
    assert result.progress.unspent_points == 5   # 1 starting + 4 gained


def test_caps_at_18_and_xp_resets():
    p = ChampProgress(champ_level=17, champ_xp=0, unspent_points=0)
    needed = champ_xp_to_next(17, tier=1)
    result = apply_champ_xp(p, tier=1, delta=needed + 9999)
    assert result.progress.champ_level == 18
    assert result.progress.champ_xp == 0
    assert result.levels_gained == 1


def test_starting_plus_levelups_equals_eighteen_points():
    """A fresh champ has 1 banked point; 17 level-ups grant 17 more = exactly 18."""
    p = ChampProgress()
    huge = champ_total_xp_to_reach(CHAMP_LEVEL_CAP, tier=3) + 10
    result = apply_champ_xp(p, tier=3, delta=huge)
    assert result.progress.champ_level == 18
    assert result.progress.unspent_points == 18   # 1 + 17 = exactly 18


def test_passive_xp_is_smaller_and_never_zero():
    assert passive_xp(100, share=0.15) == 15
    assert passive_xp(3, share=0.15) >= 1   # floors at 1
