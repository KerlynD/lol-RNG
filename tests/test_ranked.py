from bot.game.ranked import (
    BASE_LP,
    DECAY_FLOOR_LP,
    LOSS_MAG_CAP,
    PLACEMENT_BASE_LP,
    RANK_TIERS,
    SEASON_CARRY_CAP,
    WIN_GAIN_CAP,
    apply_decay,
    is_decay_eligible,
    lp_exchange,
    next_tier_floor,
    placement_starting_lp,
    season_mmr_carry,
    streak_adjusted_values,
    tier_index,
    tier_name,
)


# --- Tier boundaries ---------------------------------------------------------

def test_tier_index_at_boundaries():
    assert tier_index(0) == 0           # Iron
    assert tier_index(199) == 0
    assert tier_index(200) == 1         # Bronze
    assert tier_index(600) == 3         # Gold
    assert tier_index(1600) == len(RANK_TIERS) - 1   # Challenger
    assert tier_index(99999) == len(RANK_TIERS) - 1


def test_tier_name():
    assert tier_name(0) == "Iron"
    assert tier_name(850) == "Platinum"
    assert tier_name(2000) == "Challenger"


def test_next_tier_floor():
    assert next_tier_floor(0) == 200
    assert next_tier_floor(750) == 800
    assert next_tier_floor(1600) is None    # top of the ladder


# --- Base LP economy ---------------------------------------------------------

def test_base_exchange_is_symmetric():
    """At 50% win rate with no streaks, gains and losses cancel."""
    ex_win = lp_exchange(3, 3, attacker_won=True)
    ex_loss = lp_exchange(3, 3, attacker_won=False)
    assert ex_win.attacker_delta == BASE_LP
    assert ex_loss.attacker_delta == -BASE_LP
    assert ex_win.attacker_delta + ex_loss.attacker_delta == 0


def test_same_tier_is_symmetric_between_players():
    ex = lp_exchange(2, 2, attacker_won=True)
    assert ex.attacker_delta == BASE_LP
    assert ex.defender_delta == -BASE_LP


# --- Streak scaling ----------------------------------------------------------

def test_no_streak_below_threshold():
    sv = streak_adjusted_values(win_streak=2, loss_streak=0)
    assert sv.win_gain == BASE_LP
    assert sv.loss_amount == -BASE_LP


def test_win_streak_increases_gain_and_softens_loss():
    sv = streak_adjusted_values(win_streak=3, loss_streak=0)
    assert sv.win_gain > BASE_LP
    assert sv.loss_amount > -BASE_LP   # less negative


def test_win_streak_gain_is_capped():
    sv = streak_adjusted_values(win_streak=50, loss_streak=0)
    assert sv.win_gain == WIN_GAIN_CAP
    assert sv.loss_amount == -10       # loss magnitude floored at 10


def test_loss_streak_increases_loss_and_softens_gain():
    sv = streak_adjusted_values(win_streak=0, loss_streak=4)
    assert sv.loss_amount < -BASE_LP
    assert sv.win_gain < BASE_LP


def test_loss_streak_is_capped():
    sv = streak_adjusted_values(win_streak=0, loss_streak=50)
    assert sv.loss_amount == -LOSS_MAG_CAP
    assert sv.win_gain == 10           # win gain floored at 10


def test_win_streak_applies_to_same_tier_match():
    ex = lp_exchange(3, 3, attacker_won=True, attacker_win_streak=6)
    assert ex.attacker_delta > BASE_LP


# --- Cross-rank Elo factor ---------------------------------------------------

def test_punching_up_rewards_the_lower_ranked_attacker():
    # attacker tier 1, defender tier 4 -> attacker punches up
    ex = lp_exchange(1, 4, attacker_won=True)
    assert ex.attacker_delta == 25     # big reward
    assert ex.defender_delta == -25    # higher-ranked player punished hard


def test_punching_up_loss_is_soft_for_attacker():
    ex = lp_exchange(1, 4, attacker_won=False)
    assert ex.attacker_delta == -5
    assert ex.defender_delta == 5


def test_mild_punch_down_one_tier():
    ex = lp_exchange(4, 3, attacker_won=True)
    assert ex.attacker_delta == 5
    ex_loss = lp_exchange(4, 3, attacker_won=False)
    assert ex_loss.attacker_delta == -25


def test_rank_gap_lockout_zero_lp_on_win():
    # attacker 3 tiers above defender
    ex = lp_exchange(5, 2, attacker_won=True)
    assert ex.attacker_delta == 0
    ex_loss = lp_exchange(5, 2, attacker_won=False)
    assert ex_loss.attacker_delta == -25


def test_elo_overrides_streaks():
    """A streak must not change LP in a cross-rank match."""
    with_streak = lp_exchange(1, 4, attacker_won=True, attacker_win_streak=10)
    without = lp_exchange(1, 4, attacker_won=True)
    assert with_streak.attacker_delta == without.attacker_delta == 25


# --- Placements --------------------------------------------------------------

def test_placement_perfect_run():
    assert placement_starting_lp(wins=5, losses=0) == PLACEMENT_BASE_LP + 5 * 35


def test_placement_winless_run_clamps_non_negative():
    assert placement_starting_lp(wins=0, losses=5) >= 0


def test_placement_carry_raises_starting_lp():
    base = placement_starting_lp(wins=3, losses=2)
    carried = placement_starting_lp(wins=3, losses=2, mmr_carry=100)
    assert carried == base + 100


# --- Season MMR carry --------------------------------------------------------

def test_new_player_gets_no_carry():
    assert season_mmr_carry(PLACEMENT_BASE_LP) == 0


def test_veteran_carry_is_capped():
    assert season_mmr_carry(99999) == SEASON_CARRY_CAP


def test_carry_scales_with_mmr():
    assert season_mmr_carry(600) > season_mmr_carry(300) > 0


# --- Decay -------------------------------------------------------------------

def test_decay_only_platinum_and_above():
    assert is_decay_eligible(800) is True
    assert is_decay_eligible(799) is False


def test_decay_never_drops_below_gold():
    assert apply_decay(DECAY_FLOOR_LP + 5) == DECAY_FLOOR_LP
    assert apply_decay(DECAY_FLOOR_LP) == DECAY_FLOOR_LP


def test_decay_subtracts_lp():
    assert apply_decay(1000) == 985
