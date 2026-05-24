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


# --- Fragment redemption (v3 cross-tier conversion) -------------------------

from bot.game.economy import (
    FRAGMENT_THRESHOLDS,
    available_redeem_options,
    fragment_item_key,
    redeem_cost,
)


def test_redeem_cost_same_tier_is_threshold():
    for tier, threshold in FRAGMENT_THRESHOLDS.items():
        assert redeem_cost(tier, tier) == threshold


def test_redeem_cost_doubles_for_one_tier_up():
    assert redeem_cost(1, 2) == FRAGMENT_THRESHOLDS[1] * 2
    assert redeem_cost(3, 4) == FRAGMENT_THRESHOLDS[3] * 2


def test_redeem_cost_triples_for_two_tiers_up():
    assert redeem_cost(1, 3) == FRAGMENT_THRESHOLDS[1] * 3
    assert redeem_cost(4, 6) == FRAGMENT_THRESHOLDS[4] * 3


def test_redeem_cost_rejects_invalid_combos():
    # Wrong direction
    assert redeem_cost(3, 2) is None
    # More than +2 tiers
    assert redeem_cost(1, 4) is None
    # Beyond the T6 fragment ceiling
    assert redeem_cost(5, 7) is None


def test_available_redeem_options_filters_by_inventory_and_cap():
    inv = {
        fragment_item_key(1): FRAGMENT_THRESHOLDS[1] * 3,  # enough for T1, T2, T3
        fragment_item_key(2): FRAGMENT_THRESHOLDS[2],      # enough for T2 only
    }
    options = available_redeem_options(inv, region_tier_cap=6)
    # T1 -> T1 (×1), T1 -> T2 (×2), T1 -> T3 (×3), T2 -> T2 (×1).
    targets = {(s, t) for s, t, _ in options}
    assert (1, 1) in targets
    assert (1, 2) in targets
    assert (1, 3) in targets
    assert (2, 2) in targets
    # T2 -> T3 needs 2× T2 fragments, user only has 1× threshold worth.
    assert (2, 3) not in targets


def test_available_redeem_options_respects_region_cap():
    inv = {fragment_item_key(1): FRAGMENT_THRESHOLDS[1] * 3}
    capped = available_redeem_options(inv, region_tier_cap=2)
    targets = {t for _, t, _ in capped}
    assert max(targets) == 2  # T3 path filtered out
