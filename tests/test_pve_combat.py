import random

from bot.db.queries import Champion
from bot.game.pve.camps import CAMPS, CampSpec
from bot.game.pve.combat import (
    DEFAULT_RESPAWN_SEC,
    FAIL_GOLD_PCT,
    PVE_WIN_PCT_BY_DIFF,
    RESPAWN_DURATION_SEC,
    WEAKNESS_BONUS_PCT,
    preview_win_pct,
    resolve_camp_fight,
)


def _champ(name: str, tier: int, dmg: str = "AD") -> Champion:
    return Champion(
        id=hash(name) & 0xFFFFFF,
        name=name,
        tier=tier,
        region="X",
        factions=[],
        damage_type=dmg,
        drop_weight=0.1,
        splash_url=None,
    )


def test_win_pct_curve_monotone():
    """Lower tier diff = lower win %, strictly decreasing across the table."""
    diffs = sorted(PVE_WIN_PCT_BY_DIFF.keys(), reverse=True)
    prev = 100.0
    for d in diffs:
        assert PVE_WIN_PCT_BY_DIFF[d] <= prev
        prev = PVE_WIN_PCT_BY_DIFF[d]


def test_win_pct_matched_is_50():
    # Use a camp with no weakness so the matched base shows through.
    c = _champ("c", 1)
    camp = CAMPS["krugs"]   # tier 1, weak_to=None
    assert preview_win_pct(c, camp) == 50.0


def test_win_pct_extreme_mismatch_floors():
    c = _champ("c", 1)
    drake = CAMPS["drake_cloud"]  # tier 4
    # diff = -3 -> table floor on the rebalanced curve.
    assert preview_win_pct(c, drake) == PVE_WIN_PCT_BY_DIFF[-3]


def test_weakness_bonus_applied():
    """An AP champ vs Wolves (weak to AP) should beat base by WEAKNESS_BONUS_PCT."""
    ap = _champ("ap", 1, dmg="AP")
    ad = _champ("ad", 1, dmg="AD")
    wolves = CAMPS["wolves"]
    base = preview_win_pct(ad, wolves)
    boosted = preview_win_pct(ap, wolves)
    assert boosted == min(99.0, base + WEAKNESS_BONUS_PCT)


def test_red_buff_stacks_with_weakness():
    ap = _champ("ap", 1, dmg="AP")
    wolves = CAMPS["wolves"]
    no_buff = preview_win_pct(ap, wolves, red_buff=False)
    with_buff = preview_win_pct(ap, wolves, red_buff=True)
    # red_buff adds another flat +WEAKNESS_BONUS_PCT (capped 99)
    assert with_buff == min(99.0, no_buff + WEAKNESS_BONUS_PCT)


def test_resolve_loss_costs_fail_gold_pct():
    c = _champ("c", 1)
    drake = CAMPS["drake_cloud"]
    rng = random.Random(0)
    # diff = -3, win pct ~0.5% — most rolls should lose
    losses = 0
    sample = 200
    for _ in range(sample):
        r = resolve_camp_fight(c, drake, rng=rng)
        if not r.won:
            losses += 1
            assert r.gold_delta == -int(drake.base_gold * FAIL_GOLD_PCT)
            assert r.respawn_seconds == DEFAULT_RESPAWN_SEC  # diff <= -4 fallback; -3 uses table
    # On the rebalanced curve diff -3 wins ~12%, so the vast majority lose.
    assert losses > sample * 0.7


def test_respawn_table_keys():
    # The respawn table should cover diff = 0, -1, -2, -3 explicitly
    for d in (0, -1, -2, -3):
        assert d in RESPAWN_DURATION_SEC
        assert RESPAWN_DURATION_SEC[d] > 0
    # And the fallback is harshest
    assert DEFAULT_RESPAWN_SEC >= max(RESPAWN_DURATION_SEC.values())


def test_matched_loss_gives_5min_respawn():
    c = _champ("c", 2)
    troll = CAMPS["troll_camp"]   # tier 2
    rng = random.Random(0)
    # Force many trials, look at any loss
    sample = 500
    found_loss = False
    for _ in range(sample):
        r = resolve_camp_fight(c, troll, rng=rng)
        if not r.won:
            assert r.respawn_seconds == 5 * 60
            found_loss = True
            break
    assert found_loss


def test_win_table_symmetric_around_50():
    """Each +N entry should mirror its -N entry around the matched 50 baseline."""
    for diff, pct in PVE_WIN_PCT_BY_DIFF.items():
        opp = PVE_WIN_PCT_BY_DIFF.get(-diff)
        if opp is not None:
            assert abs((pct - 50) + (opp - 50)) < 0.5, (diff, pct, opp)


def test_champ_bonus_adds_and_clamps():
    """Champion ability bonus stacks additively and the result clamps to 1..99."""
    c = _champ("c", 3)
    camp = CAMPS["krugs"]   # tier 1 -> diff +2 -> 78 on rebalanced table
    base = preview_win_pct(c, camp)
    boosted = preview_win_pct(c, camp, champ_bonus=10)
    assert boosted == min(99.0, base + 10)
    # Massive bonus clamps at 99.
    extreme = preview_win_pct(c, camp, champ_bonus=500)
    assert extreme == 99.0
    # Negative champ bonus on top of a -4 result floors at 1.
    weak = _champ("w", 1)
    drake = CAMPS["drake_infernal"]
    floored = preview_win_pct(weak, drake, champ_bonus=-500)
    assert floored == 1.0


def test_revive_potion_drops_approx_2pct():
    """The 2% revive-potion drop fires on wins across the camp pool."""
    from bot.game.pve.combat import REVIVE_POTION_DROP_CHANCE
    c = _champ("c", 6)
    camp = CAMPS["krugs"]
    rng = random.Random(7)
    wins = 0
    revives = 0
    for _ in range(2000):
        r = resolve_camp_fight(c, camp, rng=rng)
        if r.won:
            wins += 1
            if any(t == "revive_potion" for t, _ in r.drops):
                revives += 1
    rate = revives / wins
    # Generous bounds around the configured probability.
    assert REVIVE_POTION_DROP_CHANCE * 0.4 < rate < REVIVE_POTION_DROP_CHANCE * 2.0


def test_winning_camp_gives_drops_when_certain():
    """100% drops should always drop on win."""
    c = _champ("c", 6)  # very high tier vs a Tier 2 camp
    camp = CAMPS["red_brambleback"]  # drops red_buff at 100%
    rng = random.Random(42)
    # All 50 trials should be wins (diff +4 = 99%) and red_buff should drop each time
    for _ in range(50):
        r = resolve_camp_fight(c, camp, rng=rng)
        if r.won:
            assert any(t == "red_buff" for t, _ in r.drops)
