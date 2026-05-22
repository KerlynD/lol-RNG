"""PvP combat (PRD §5.2): Power scores + best-of-3 multi-round skirmish.

Hidden d100 per round preserves drama; loadout composition determines odds.
All damage / shield logic is here — pure functions over Champion + loadout.
"""
from __future__ import annotations

import hashlib
import random
import struct
from dataclasses import dataclass

from bot.db.queries import Champion, LoadoutEntry
from bot.game.champions.abilities import progress_win_bonus

# --- Per-tier base stats -----------------------------------------------------
#
# (HP, ATK, DEF) baseline for each tier. We derive per-champion variance from
# a stable hash of the champion name so stats are deterministic across runs
# without needing extra DB columns.

_TIER_BASE_STATS: dict[int, tuple[int, int, int]] = {
    1: (40,  30,  15),
    2: (55,  40,  20),
    3: (75,  55,  28),
    4: (100, 75,  38),
    5: (135, 100, 50),
    6: (180, 135, 65),
    7: (220, 165, 80),
}

# Per-champion variance: ±15% of base for each stat, derived deterministically.
_VARIANCE_RANGE = 0.15

POWER_HP_WEIGHT = 0.4
POWER_ATK_WEIGHT = 0.4
POWER_DEF_WEIGHT = 0.2

# Tier-difference power modifier (PRD §5.2): +5% per tier of advantage, capped.
TIER_DIFF_BONUS_PER_STEP = 0.05
TIER_DIFF_BONUS_CAP = 0.25

# Per-level minor boost (rewards leveling without making low-pulls useless).
LEVEL_POWER_BONUS_PER_LEVEL = 0.01

# Win probability clamp (PRD §5.2: soft-clamped to [10, 90]).
WIN_PCT_MIN = 10
WIN_PCT_MAX = 90


@dataclass(frozen=True)
class CombatStats:
    hp: int
    atk: int
    def_: int


def _variance_factor(name: str, stat_key: str) -> float:
    """Deterministic factor in [1 - V, 1 + V] for a (champ, stat) pair."""
    digest = hashlib.sha256(f"stats|{name}|{stat_key}".encode("utf-8")).digest()
    (raw,) = struct.unpack(">Q", digest[:8])
    unit = raw / 2**64                  # [0, 1)
    return 1.0 + (unit * 2 - 1) * _VARIANCE_RANGE


def champion_stats(champ: Champion) -> CombatStats:
    base_hp, base_atk, base_def = _TIER_BASE_STATS[champ.tier]
    return CombatStats(
        hp=int(round(base_hp * _variance_factor(champ.name, "hp"))),
        atk=int(round(base_atk * _variance_factor(champ.name, "atk"))),
        def_=int(round(base_def * _variance_factor(champ.name, "def"))),
    )


def power_score(champ: Champion, level: int = 1, prestige: int = 0) -> float:
    stats = champion_stats(champ)
    raw = (
        stats.hp * POWER_HP_WEIGHT
        + stats.atk * POWER_ATK_WEIGHT
        + stats.def_ * POWER_DEF_WEIGHT
    )
    level_mult = 1.0 + LEVEL_POWER_BONUS_PER_LEVEL * max(0, level - 1)
    prestige_mult = 1.0 + 0.02 * max(0, prestige)
    return raw * level_mult * prestige_mult


def _tier_diff_modifier(attacker_tier: int, defender_tier: int) -> float:
    diff = attacker_tier - defender_tier
    bonus = min(TIER_DIFF_BONUS_CAP, max(-TIER_DIFF_BONUS_CAP, diff * TIER_DIFF_BONUS_PER_STEP))
    return 1.0 + bonus


def _win_pct(attacker_power: float, defender_power: float) -> int:
    total = attacker_power + defender_power
    if total <= 0:
        return 50
    pct = round(100 * attacker_power / total)
    return max(WIN_PCT_MIN, min(WIN_PCT_MAX, pct))


# --- Round + skirmish --------------------------------------------------------


@dataclass(frozen=True)
class RoundResult:
    attacker_champ: Champion
    defender_champ: Champion
    win_pct: int               # attacker's hidden win % (for logs/debug, NOT shown live)
    attacker_won: bool
    shield_consumed: str | None  # 'shield_physical' | 'shield_magic' | 'aegis' | 'stasis' | None
    flavor: str


@dataclass(frozen=True)
class SkirmishResult:
    attacker_won: bool
    rounds: list[RoundResult]
    rounds_won_by_attacker: int
    rounds_won_by_defender: int


FLAVOR_WIN = [
    "{atk} overwhelms {def_} in a single brutal exchange.",
    "{atk} cuts down {def_} before they can react.",
    "{atk} outmaneuvers {def_} and lands the killing blow.",
    "{def_} is no match for {atk}'s onslaught.",
]
FLAVOR_LOSS = [
    "{def_} weathers {atk}'s assault and counters cleanly.",
    "{atk} overextends — {def_} punishes the opening.",
    "{def_} reads {atk}'s attack and turns the duel around.",
    "{atk} falls back, bested by {def_}.",
]
FLAVOR_SHIELD = [
    "{def_}'s {shield_name} absorbs the blow — they recover and strike back.",
    "{shield_name} shimmers — {def_} survives and finishes {atk}.",
]


def _pick_defender_champ(
    defender_loadout: list[LoadoutEntry],
    attacker_damage_type: str,
    used_ids: set[int],
) -> Champion | None:
    """Pick defender's best counter to the attacker's damage type."""
    candidates = [e.champion for e in defender_loadout if e.champion.id not in used_ids]
    if not candidates:
        return None
    # Best counter: highest DEF, weighted slightly for damage-type counter.
    def score(c: Champion) -> float:
        s = champion_stats(c)
        bias = 0.0
        if attacker_damage_type == "AD" and c.damage_type in ("AD", "Hybrid"):
            bias += 5
        if attacker_damage_type == "AP" and c.damage_type in ("AP", "Hybrid"):
            bias += 5
        return s.def_ + bias
    return max(candidates, key=score)


def _pick_attacker_champ(
    attacker_loadout: list[LoadoutEntry],
    used_ids: set[int],
    level: int,
    prestige: int,
) -> Champion | None:
    candidates = [e.champion for e in attacker_loadout if e.champion.id not in used_ids]
    if not candidates:
        return None
    return max(candidates, key=lambda c: power_score(c, level=level, prestige=prestige))


def simulate_round(
    attacker_champ: Champion,
    defender_champ: Champion,
    attacker_level: int,
    defender_level: int,
    attacker_prestige: int,
    defender_prestige: int,
    defender_shields: dict[str, int],
    attacker_power_multiplier: float = 1.0,
    attacker_champ_bonus: float = 0.0,
    defender_champ_bonus: float = 0.0,
    rng: random.Random | None = None,
) -> RoundResult:
    rng = rng or random
    atk_power = (
        power_score(attacker_champ, attacker_level, attacker_prestige)
        * _tier_diff_modifier(attacker_champ.tier, defender_champ.tier)
        * attacker_power_multiplier
    )
    def_power = power_score(defender_champ, defender_level, defender_prestige)
    win_pct = _win_pct(atk_power, def_power)
    # Champion ability ranks shift the round odds (PvP champ-level bonus).
    win_pct = max(
        WIN_PCT_MIN,
        min(WIN_PCT_MAX, round(win_pct + attacker_champ_bonus - defender_champ_bonus)),
    )
    roll = rng.randint(1, 100)
    attacker_won = roll <= win_pct

    shield_consumed: str | None = None
    flavor: str

    if attacker_won:
        # Defender takes a hit — check typed shield first.
        damage_type = attacker_champ.damage_type
        shield_priority: list[str] = []
        if damage_type == "AD":
            shield_priority = ["shield_physical", "aegis", "stasis"]
        elif damage_type == "AP":
            shield_priority = ["shield_magic", "aegis", "stasis"]
        else:  # Hybrid
            shield_priority = ["aegis", "shield_physical", "shield_magic", "stasis"]

        for shield_type in shield_priority:
            if defender_shields.get(shield_type, 0) > 0:
                shield_consumed = shield_type
                defender_shields[shield_type] -= 1
                attacker_won = False  # shield saves the round → defender wins
                break

        if shield_consumed:
            shield_name = {
                "shield_physical": "Physical Shield",
                "shield_magic": "Magic Shield",
                "aegis": "Aegis",
                "stasis": "Stasis",
            }[shield_consumed]
            flavor = rng.choice(FLAVOR_SHIELD).format(
                atk=attacker_champ.name, def_=defender_champ.name, shield_name=shield_name
            )
        else:
            flavor = rng.choice(FLAVOR_WIN).format(
                atk=attacker_champ.name, def_=defender_champ.name
            )
    else:
        flavor = rng.choice(FLAVOR_LOSS).format(
            atk=attacker_champ.name, def_=defender_champ.name
        )

    return RoundResult(
        attacker_champ=attacker_champ,
        defender_champ=defender_champ,
        win_pct=win_pct,
        attacker_won=attacker_won,
        shield_consumed=shield_consumed,
        flavor=flavor,
    )


def simulate_skirmish(
    attacker_loadout: list[LoadoutEntry],
    defender_loadout: list[LoadoutEntry],
    *,
    attacker_level: int = 1,
    defender_level: int = 1,
    attacker_prestige: int = 0,
    defender_prestige: int = 0,
    attacker_power_multiplier: float = 1.0,
    defender_shields: dict[str, int] | None = None,
    best_of: int = 3,
    rng: random.Random | None = None,
) -> SkirmishResult:
    """Best-of-`best_of` skirmish (use best_of=1 for a single-round duel).
    Shields are consumed in place from the passed-in dict.

    `attacker_power_multiplier` lets buffs (e.g. red_buff) inflate the
    attacker's effective Power without touching combat math elsewhere.
    """
    if not attacker_loadout:
        raise ValueError("Attacker has no equipped champions.")
    if not defender_loadout:
        raise ValueError("Defender has no equipped champions.")
    if best_of < 1:
        raise ValueError("best_of must be at least 1.")

    rng = rng or random
    shields = dict(defender_shields or {})
    rounds_to_win = best_of // 2 + 1

    # Per-owned champion-level ability bonus, keyed by champion id per side.
    atk_bonus_by_id = {e.champion.id: progress_win_bonus(e.progress) for e in attacker_loadout}
    def_bonus_by_id = {e.champion.id: progress_win_bonus(e.progress) for e in defender_loadout}

    used_attackers: set[int] = set()
    used_defenders: set[int] = set()
    rounds: list[RoundResult] = []
    a_wins = 0
    d_wins = 0

    for _ in range(best_of):
        a_champ = _pick_attacker_champ(
            attacker_loadout, used_attackers, attacker_level, attacker_prestige
        ) or attacker_loadout[0].champion
        d_champ = _pick_defender_champ(
            defender_loadout, a_champ.damage_type, used_defenders
        ) or defender_loadout[0].champion

        result = simulate_round(
            a_champ, d_champ,
            attacker_level=attacker_level,
            defender_level=defender_level,
            attacker_prestige=attacker_prestige,
            defender_prestige=defender_prestige,
            defender_shields=shields,
            attacker_power_multiplier=attacker_power_multiplier,
            attacker_champ_bonus=atk_bonus_by_id.get(a_champ.id, 0.0),
            defender_champ_bonus=def_bonus_by_id.get(d_champ.id, 0.0),
            rng=rng,
        )
        rounds.append(result)
        used_attackers.add(a_champ.id)
        used_defenders.add(d_champ.id)

        if result.attacker_won:
            a_wins += 1
        else:
            d_wins += 1
        if a_wins >= rounds_to_win or d_wins >= rounds_to_win:
            break

    # Mutate the caller's dict so they know what was consumed.
    if defender_shields is not None:
        defender_shields.clear()
        defender_shields.update(shields)

    return SkirmishResult(
        attacker_won=a_wins > d_wins,
        rounds=rounds,
        rounds_won_by_attacker=a_wins,
        rounds_won_by_defender=d_wins,
    )
