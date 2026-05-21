"""Sanity check: PVE Gold/hour outpaces classic action Gold/hour (PRD v2 §D).

Computes idealized Gold rates assuming average win % at matched tier and
mean cooldown durations. PVE should be 2-3x more efficient than the action
loop at meaningful levels.
"""
from statistics import mean

from bot.game.actions.registry import ACTIONS
from bot.game.economy import gold_payout
from bot.game.pve.camps import CAMPS, ENCOUNTER_POOL
from bot.game.pve.combat import PVE_WIN_PCT_BY_DIFF


def _avg_cooldown(spec) -> float:
    return spec.cooldown.total_seconds()


def _pve_gold_per_hour(level: int) -> float:
    """Expected gold/hour from /hunt-camp at a given level.

    Players draw from the encounter pool; we use the weighted average
    base_gold across the pool, multiplied by expected win % at matched tier
    (50%) and the level scaling. Average cooldown is the pool's mean.
    """
    # Average base_gold and mean cooldown across the pool
    total_weight = sum(w for _, w in ENCOUNTER_POOL)
    weighted_gold = 0.0
    weighted_cd = 0.0
    for keys, w in ENCOUNTER_POOL:
        bucket_avg_gold = mean(CAMPS[k].base_gold for k in keys)
        bucket_avg_cd = mean(
            (CAMPS[k].cooldown_range[0] + CAMPS[k].cooldown_range[1]) / 2
            for k in keys
        )
        weighted_gold += (w / total_weight) * bucket_avg_gold
        weighted_cd += (w / total_weight) * bucket_avg_cd

    # 50% win rate at matched tier — losses cost 20% of base_gold.
    win_pct = PVE_WIN_PCT_BY_DIFF[0] / 100.0
    expected_per_encounter = (
        win_pct * weighted_gold - (1 - win_pct) * 0.2 * weighted_gold
    )
    scaled = gold_payout(int(expected_per_encounter), level)
    return scaled * (3600.0 / weighted_cd)


def _action_gold_per_hour(level: int) -> float:
    """Expected gold/hour if a player spammed every action they could at this level."""
    # Sum gold/hour contributions from every action with cooldown <= 24h.
    total = 0.0
    for spec in ACTIONS.values():
        if spec.tier > 5:
            continue
        cd_sec = _avg_cooldown(spec)
        if cd_sec <= 0:
            continue
        scaled = gold_payout(spec.base_gold, level)
        total += scaled * 3600.0 / cd_sec
    return total


def test_pve_beats_actions_at_l5():
    pve = _pve_gold_per_hour(5)
    actions = _action_gold_per_hour(5)
    assert pve > actions * 2.0, f"PVE {pve:.0f}/h vs actions {actions:.0f}/h"


def test_pve_beats_actions_at_l15():
    pve = _pve_gold_per_hour(15)
    actions = _action_gold_per_hour(15)
    assert pve > actions * 2.0, f"PVE {pve:.0f}/h vs actions {actions:.0f}/h"


def test_pve_beats_actions_at_l25():
    pve = _pve_gold_per_hour(25)
    actions = _action_gold_per_hour(25)
    assert pve > actions * 2.0, f"PVE {pve:.0f}/h vs actions {actions:.0f}/h"


def test_daily_action_remains_lucrative_login_bonus():
    """Even after rebalance, /daily should be the biggest single instant payout among T1."""
    daily = ACTIONS["daily"]
    work = ACTIONS["work"]
    assert daily.base_gold > work.base_gold * 5
