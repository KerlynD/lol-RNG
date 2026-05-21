import random

from bot.db.queries import Champion, LoadoutEntry
from bot.game.combat import (
    champion_stats,
    power_score,
    simulate_round,
    simulate_skirmish,
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


def test_champion_stats_deterministic():
    c = _champ("Garen", 2)
    assert champion_stats(c) == champion_stats(c)


def test_power_scales_with_tier():
    p1 = power_score(_champ("low", 1))
    p7 = power_score(_champ("high", 7))
    assert p7 > p1 * 2  # generous bound — tier ramps are real


def test_power_scales_with_level():
    c = _champ("x", 3)
    assert power_score(c, level=20) > power_score(c, level=1)


def test_simulate_round_attacker_advantaged():
    # Attacker T6 vs Defender T1 — attacker should win most rounds.
    atk = _champ("god", 6)
    def_ = _champ("min", 1)
    wins = 0
    rng = random.Random(2024)
    for _ in range(500):
        r = simulate_round(
            atk, def_,
            attacker_level=10, defender_level=10,
            attacker_prestige=0, defender_prestige=0,
            defender_shields={},
            rng=rng,
        )
        wins += int(r.attacker_won)
    assert wins > 400


def test_simulate_round_shield_saves():
    atk = _champ("ad-atk", 4, dmg="AD")
    def_ = _champ("def", 3)
    shields = {"shield_physical": 1, "shield_magic": 0, "aegis": 0, "stasis": 0}
    rng = random.Random(0)
    saved_at_least_once = False
    for _ in range(20):
        r = simulate_round(
            atk, def_,
            attacker_level=5, defender_level=5,
            attacker_prestige=0, defender_prestige=0,
            defender_shields=shields,
            rng=rng,
        )
        if r.shield_consumed == "shield_physical":
            saved_at_least_once = True
            break
    assert saved_at_least_once  # at the first shield consumption attempt, shield should pop
    assert shields["shield_physical"] == 0


def test_simulate_skirmish_best_of_3():
    atk_load = [LoadoutEntry(slot=i + 1, champion=_champ(f"a{i}", 3)) for i in range(3)]
    def_load = [LoadoutEntry(slot=i + 1, champion=_champ(f"d{i}", 3)) for i in range(3)]
    rng = random.Random(7)
    result = simulate_skirmish(atk_load, def_load, rng=rng)
    assert len(result.rounds) in (2, 3)
    assert result.rounds_won_by_attacker + result.rounds_won_by_defender == len(result.rounds)
    assert (result.rounds_won_by_attacker >= 2) ^ (result.rounds_won_by_defender >= 2)


def test_simulate_skirmish_consumes_shields_inplace():
    atk_load = [LoadoutEntry(slot=1, champion=_champ("atk", 5, dmg="AD"))]
    def_load = [LoadoutEntry(slot=1, champion=_champ("def", 2))]
    shields = {"shield_physical": 3, "shield_magic": 0, "aegis": 0, "stasis": 0}
    rng = random.Random(11)
    simulate_skirmish(
        atk_load, def_load,
        attacker_level=20, defender_level=5,
        defender_shields=shields, rng=rng,
    )
    # The attacker should land at least one hit out of 3 rounds against a much weaker defender,
    # consuming at least one shield.
    assert shields["shield_physical"] < 3
