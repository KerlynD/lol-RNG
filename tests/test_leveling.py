from bot.game.leveling import (
    LEVEL_CAP,
    apply_xp,
    total_xp_to_reach,
    unlocks_for,
    xp_to_next_level,
)


def test_unlocks_monotone_loadout_slots():
    prev = 0
    for L in (1, 5, 10, 15, 20, 25, 30):
        slots = unlocks_for(L).loadout_slots
        assert slots >= prev
        prev = slots
    assert unlocks_for(LEVEL_CAP).loadout_slots == 5


def test_unlocks_action_tier_monotone():
    prev = 0
    for L in range(1, 31):
        u = unlocks_for(L)
        assert u.max_action_tier >= prev
        prev = u.max_action_tier
    assert unlocks_for(25).max_action_tier == 7
    assert unlocks_for(30).max_action_tier == 7


def test_can_prestige_only_at_30():
    for L in range(1, 30):
        assert unlocks_for(L).can_prestige is False
    assert unlocks_for(30).can_prestige is True


def test_xp_to_next_level_monotone_and_positive():
    last = 0
    for L in range(1, LEVEL_CAP):
        cost = xp_to_next_level(L)
        assert cost > 0
        assert cost >= last
        last = cost
    assert xp_to_next_level(LEVEL_CAP) == 0


def test_apply_xp_single_level_up():
    result = apply_xp(0, 1, xp_to_next_level(1))
    assert result.new_level == 2
    assert result.leveled_up_to == 2
    assert result.new_xp == 0


def test_apply_xp_cascade_multi_level():
    big = sum(xp_to_next_level(L) for L in range(1, 5))
    result = apply_xp(0, 1, big)
    assert result.new_level == 5
    assert result.leveled_up_to == 5
    assert result.new_xp == 0


def test_apply_xp_caps_at_level_cap():
    result = apply_xp(0, 1, 10_000_000)
    assert result.new_level == LEVEL_CAP
    assert result.new_xp == 0


def test_apply_xp_no_op_at_cap():
    r = apply_xp(0, LEVEL_CAP, 500)
    assert r.new_level == LEVEL_CAP
    assert r.leveled_up_to is None
    assert r.new_xp == 0


def test_total_xp_to_reach_30_is_in_target_range():
    total = total_xp_to_reach(LEVEL_CAP)
    assert 30_000 <= total <= 200_000
