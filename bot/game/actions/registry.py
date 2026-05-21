"""Static catalog of every PRD action. One ActionSpec per command.

Adding a new action = add an entry here + register the slash command in
bot/cogs/actions.py (or another cog). All gating + payout flows through
bot/game/actions/runner.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta


@dataclass(frozen=True)
class ActionSpec:
    key: str
    name: str                                 # display name, e.g. "/work"
    tier: int                                 # 1..7 — for cooldown defaults + thematic grouping
    cooldown: timedelta
    min_champ_tier: int = 0                   # 0 = no champ requirement
    required_region: str | None = None
    required_factions: tuple[str, ...] = ()
    required_champion: str | None = None
    base_gold: int = 0
    base_xp: int = 0
    drop_table: tuple[tuple[str, float], ...] = ()   # ((item_type, probability), ...)
    triggers_pvp: bool = False
    description: str = ""


def _cd(hours: float = 0, minutes: float = 0, days: float = 0) -> timedelta:
    return timedelta(hours=hours, minutes=minutes, days=days)


# ============================================================================
# Tier 1 — Common (no champ required)
# ============================================================================
T1: tuple[ActionSpec, ...] = (
    ActionSpec(
        key="work", name="/work", tier=1, cooldown=_cd(hours=1),
        base_gold=50, base_xp=8,
        drop_table=(("shield_physical", 0.05),),
        description="Honest labor for honest pay.",
    ),
    ActionSpec(
        key="beg", name="/beg", tier=1, cooldown=_cd(minutes=30),
        base_gold=15, base_xp=3,
        description="A few coins from strangers. Or none.",
    ),
    ActionSpec(
        key="daily", name="/daily", tier=1, cooldown=_cd(hours=24),
        base_gold=500, base_xp=50,
        drop_table=(("roll_token", 1.0),),     # always grants 1 token
        description="Your daily reward.",
    ),
)

# ============================================================================
# Tier 2 — Uncommon (region/faction or any T2+ champ)
# ============================================================================
T2: tuple[ActionSpec, ...] = (
    ActionSpec(
        key="forage", name="/forage", tier=2, cooldown=_cd(hours=1, minutes=30),
        required_factions=("Yordle",),
        base_gold=56, base_xp=12,                       # -30% rebalance vs PVE (v2)
        drop_table=(("mat", 0.5), ("shield_physical", 0.05)),
        description="Bandle City foraging.",
    ),
    ActionSpec(
        key="tinker", name="/tinker", tier=2, cooldown=_cd(hours=2),
        required_region="Piltover",  # OR Zaun OR Yordle inventor; runner accepts either-of via factions
        base_gold=49, base_xp=15,                       # -30%
        drop_table=(("mat", 0.7),),
        description="Build tools that buff other actions.",
    ),
    ActionSpec(
        key="prank", name="/prank", tier=2, cooldown=_cd(hours=1),
        min_champ_tier=2,
        base_gold=21, base_xp=10,                       # -30%
        triggers_pvp=True,
        description="Steal a small share of another player's gold.",
    ),
    ActionSpec(
        key="duel", name="/duel", tier=2, cooldown=_cd(hours=1),
        min_champ_tier=2,
        base_gold=28, base_xp=12,                       # -30%
        triggers_pvp=True,
        description="Single-round PvP against another player.",
    ),
)

# ============================================================================
# Tier 3 — Rare (regional / faction)
# ============================================================================
T3: tuple[ActionSpec, ...] = (
    ActionSpec(
        key="patrol-demacia", name="/patrol-demacia", tier=3, cooldown=_cd(hours=4),
        required_region="Demacia",
        base_gold=126, base_xp=35,                      # -30%
        drop_table=(("shield_physical", 0.25),),
        description="Demacian patrol. Steady gold, blocks AP.",
    ),
    ActionSpec(
        key="heist-piltover", name="/heist-piltover", tier=3, cooldown=_cd(hours=5),
        required_region="Piltover",
        base_gold=175, base_xp=40,                      # -30%
        drop_table=(("mat", 0.4),),
        triggers_pvp=True,
        description="High-variance Piltover heist.",
    ),
    ActionSpec(
        key="meditate-ionia", name="/meditate-ionia", tier=3, cooldown=_cd(hours=4),
        required_region="Ionia",
        base_gold=112, base_xp=50,                      # -30%
        drop_table=(("shield_magic", 0.25),),
        description="Ionian meditation. Passive XP buff.",
    ),
    ActionSpec(
        key="hunt-shadowisles", name="/hunt-shadowisles", tier=3, cooldown=_cd(hours=6),
        required_region="Shadow Isles",
        base_gold=140, base_xp=45,                      # -30%
        drop_table=(("soul", 0.5),),
        description="Hunt in the Shadow Isles.",
    ),
    ActionSpec(
        key="raid-noxus", name="/raid-noxus", tier=3, cooldown=_cd(hours=5),
        required_region="Noxus",
        base_gold=154, base_xp=45,                      # -30%
        triggers_pvp=True,
        description="Noxian raid — pure PvP for gold.",
    ),
)

# ============================================================================
# Tier 4 — Epic (faction power)
# ============================================================================
T4: tuple[ActionSpec, ...] = (
    ActionSpec(
        key="ascend", name="/ascend", tier=4, cooldown=_cd(hours=12),
        required_factions=("Ascended",),
        base_gold=280, base_xp=80,                      # -30%
        drop_table=(("fragment_t3", 0.3),),
        description="Shuriman ascension. Convert mats to fragments.",
    ),
    ActionSpec(
        key="darkin-pact", name="/darkin-pact", tier=4, cooldown=_cd(hours=12),
        required_factions=("Darkin",),
        base_gold=420, base_xp=100,                     # -30%
        drop_table=(("corruption_stack", 1.0),),
        description="Sacrifice for gold and corruption.",
    ),
    ActionSpec(
        key="defend-targon", name="/defend-targon", tier=4, cooldown=_cd(hours=12),
        required_region="Targon",
        base_gold=315, base_xp=90,                      # -30%
        drop_table=(("aegis", 0.05),),
        description="Targonian defense.",
    ),
    ActionSpec(
        key="void-touch", name="/void-touch", tier=4, cooldown=_cd(hours=12),
        required_factions=("Voidborn",),
        base_gold=350, base_xp=95,                      # -30%
        drop_table=(("soul", 0.3),),
        description="Voidborn touch. Drain target gold.",
    ),
)

# ============================================================================
# Tier 5 — Legendary
# ============================================================================
T5: tuple[ActionSpec, ...] = (
    ActionSpec(
        key="void-incursion", name="/void-incursion", tier=5, cooldown=_cd(hours=24),
        required_factions=("Voidborn",),
        min_champ_tier=5,
        base_gold=840, base_xp=200,                     # -30%
        drop_table=(("fragment_t4", 0.4), ("soul", 0.5)),
        description="Voidborn incursion. Heavy payout.",
    ),
    ActionSpec(
        key="celestial-gaze", name="/celestial-gaze", tier=5, cooldown=_cd(hours=24),
        required_factions=("Celestial", "Aspect"),
        base_gold=630, base_xp=180,                     # -30%
        drop_table=(("shield_magic", 0.4), ("aegis", 0.1)),
        description="Peek at the next roll's tier.",
    ),
    ActionSpec(
        key="freljord-storm", name="/freljord-storm", tier=5, cooldown=_cd(hours=24),
        required_region="Freljord",
        min_champ_tier=5,
        base_gold=700, base_xp=200,                     # -30%
        drop_table=(("mat", 1.0), ("shield_physical", 0.3)),
        description="Freljord storm. Area buff to your next actions.",
    ),
    ActionSpec(
        key="judgment", name="/judgment", tier=5, cooldown=_cd(hours=24),
        required_factions=("Aspect",),
        min_champ_tier=5,
        base_gold=560, base_xp=180,                     # -30%
        drop_table=(("stasis", 0.2),),
        description="Mark a player — their next PvP attempt on you fails.",
    ),
)

# ============================================================================
# Tier 6 — God (weekly cooldown) — handled in dedicated cog logic
# ============================================================================
T6: tuple[ActionSpec, ...] = (
    ActionSpec(
        key="reshape-stars", name="/reshape-stars", tier=6, cooldown=_cd(days=7),
        required_champion="Aurelion Sol",
        base_gold=0, base_xp=500,
        description="Re-roll an owned champion within the same tier.",
    ),
    ActionSpec(
        key="world-ender", name="/world-ender", tier=6, cooldown=_cd(days=7),
        required_champion="Aatrox",
        base_gold=0, base_xp=500,
        description="24h war: your PvP wins pay double; you can be attacked freely.",
    ),
    ActionSpec(
        key="wander", name="/wander", tier=6, cooldown=_cd(days=7),
        required_champion="Bard",
        base_gold=0, base_xp=500,
        description="Execute any T1–T4 action for free, ignoring cooldown.",
    ),
    ActionSpec(
        key="portal", name="/portal", tier=6, cooldown=_cd(days=7),
        required_champion="Zoe",
        base_gold=0, base_xp=500,
        description="Open a same-tier champion swap with another user.",
    ),
)

# ============================================================================
# Tier 7 — Death (Kindred only, monthly)
# ============================================================================
T7: tuple[ActionSpec, ...] = (
    ActionSpec(
        key="reap", name="/reap", tier=7, cooldown=_cd(days=30),
        required_champion="Kindred",
        base_gold=0, base_xp=1000,
        description="Mark a player. Their next unique pull diverts to you. (7 days)",
    ),
    ActionSpec(
        key="lambs-respite", name="/lambs-respite", tier=7, cooldown=_cd(days=30),
        required_champion="Kindred",
        base_gold=0, base_xp=1000,
        description="72h total PvP immunity.",
    ),
    ActionSpec(
        key="eternal-hunt", name="/eternal-hunt", tier=7, cooldown=_cd(days=30),
        required_champion="Kindred",
        base_gold=0, base_xp=1000,
        description="See another user's loadout, gold, and shields for 7 days.",
    ),
    ActionSpec(
        key="never-one-without-the-other", name="/never-one-without-the-other",
        tier=7, cooldown=_cd(days=30),
        required_champion="Kindred",
        base_gold=0, base_xp=1000,
        drop_table=(("kindred_passive", 1.0),),
        description="Auto-tie the next incoming PvP attempt against you.",
    ),
)

# ============================================================================
# Registry
# ============================================================================
ALL_SPECS: tuple[ActionSpec, ...] = T1 + T2 + T3 + T4 + T5 + T6 + T7
ACTIONS: dict[str, ActionSpec] = {s.key: s for s in ALL_SPECS}


def get_spec(key: str) -> ActionSpec:
    if key not in ACTIONS:
        raise KeyError(f"Unknown action key: {key}")
    return ACTIONS[key]
