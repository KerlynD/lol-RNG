from bot.game.economy import (
    FRAGMENT_THRESHOLDS,
    ROLL_COSTS,
    TRADE_TAX_GOLD,
    fragment_item_key,
    gold_payout,
)


def test_roll_costs_scale_with_multiplier():
    assert ROLL_COSTS[10] == ROLL_COSTS[1] * 10
    assert ROLL_COSTS[100] == ROLL_COSTS[1] * 100
    assert ROLL_COSTS[1000] == ROLL_COSTS[1] * 1000


def test_fragment_thresholds_have_no_t7():
    assert 7 not in FRAGMENT_THRESHOLDS
    for t in range(1, 7):
        assert FRAGMENT_THRESHOLDS[t] >= 1


def test_fragment_item_key():
    assert fragment_item_key(3) == "fragment_t3"


def test_trade_tax_is_positive_int():
    assert isinstance(TRADE_TAX_GOLD, int) and TRADE_TAX_GOLD > 0


def test_gold_payout_grows_with_level_and_caps():
    base = 100
    assert gold_payout(base, 1) == base
    assert gold_payout(base, 10) > gold_payout(base, 5) > gold_payout(base, 1)
    # Cap should bite well before L100
    assert gold_payout(base, 100) <= base * 5 + 1


def test_gold_payout_prestige_bonus():
    base = 100
    assert gold_payout(base, 10, prestige=1) > gold_payout(base, 10, prestige=0)


def test_gold_payout_zero_base():
    assert gold_payout(0, 30, prestige=5) == 0
