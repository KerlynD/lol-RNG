"""Tests for ability ranks + win-% bonus (bot/game/champions/abilities)."""
from __future__ import annotations

from dataclasses import replace

from bot.db.queries import ChampProgress
from bot.game.champions.abilities import (
    QWE_RANK_BONUS,
    R_LEVEL_GATES,
    R_RANK_BONUS,
    ability_win_bonus,
    apply_rank,
    can_rank,
    progress_win_bonus,
)


def test_zero_ranks_zero_bonus():
    assert ability_win_bonus(0, 0, 0, 0) == 0.0


def test_maxed_bonus():
    # 5+5+5 Q/W/E + 3 R, with R worth more per rank.
    expected = 15 * QWE_RANK_BONUS + 3 * R_RANK_BONUS
    assert ability_win_bonus(5, 5, 5, 3) == expected
    assert progress_win_bonus(
        ChampProgress(q_rank=5, w_rank=5, e_rank=5, r_rank=3)
    ) == expected


def test_r_gates_at_real_levels():
    # No points -> nothing rankable.
    assert not can_rank("r", ChampProgress(unspent_points=0))
    # Level 5 + point -> still locked (rank 1 needs level 6).
    p = ChampProgress(champ_level=5, unspent_points=1)
    assert not can_rank("r", p)
    # Level 6 -> rank 1 ok.
    assert can_rank("r", replace(p, champ_level=R_LEVEL_GATES[1]))
    # Rank 1 + level 6 -> rank 2 still locked (needs 11).
    p2 = ChampProgress(champ_level=6, r_rank=1, unspent_points=1)
    assert not can_rank("r", p2)
    assert can_rank("r", replace(p2, champ_level=R_LEVEL_GATES[2]))
    # Final R rank needs level 16.
    p3 = ChampProgress(champ_level=15, r_rank=2, unspent_points=1)
    assert not can_rank("r", p3)
    assert can_rank("r", replace(p3, champ_level=R_LEVEL_GATES[3]))


def test_qwe_capped_at_5():
    assert can_rank("q", ChampProgress(q_rank=4, unspent_points=1))
    assert not can_rank("q", ChampProgress(q_rank=5, unspent_points=1))


def test_no_points_disables_all():
    p = ChampProgress(champ_level=18, unspent_points=0)
    assert not can_rank("q", p)
    assert not can_rank("w", p)
    assert not can_rank("e", p)
    assert not can_rank("r", p)


def test_unknown_ability_rejected():
    assert not can_rank("p", ChampProgress(unspent_points=1))


def test_spending_all_18_points_reaches_max_qwer():
    """Greedily spending points (Q/W/E first, then R when gated) maxes the kit."""
    p = ChampProgress(champ_level=18, unspent_points=18)
    spend_order = (
        # Spend Q/W/E rank 1 in parallel, then R as gates open.
        ["q", "w", "e", "q", "w"]                       # 5 pts, all gated below R
        + ["r"]                                          # R1 at level 6+ (we're at 18)
        + ["e", "q", "w", "e", "q"]                      # 5 more pts on Q/W/E
        + ["r"]                                          # R2
        + ["w", "e", "q", "w", "e"]                      # 5 more pts -> Q5 W5 E5
        + ["r"]                                          # R3 (level 16+)
    )
    assert len(spend_order) == 18
    for ability in spend_order:
        assert can_rank(ability, p)
        p = apply_rank(p, ability)
    assert (p.q_rank, p.w_rank, p.e_rank, p.r_rank) == (5, 5, 5, 3)
    assert p.unspent_points == 0
