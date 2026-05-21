"""Regional exploration encounters (PRD v2 Phase C).

Each region has a small pool of vignettes. Each vignette is one of:
- 'combat'   — single PVE fight against a region-themed mob
- 'treasure' — Gold + chance of mat/fragment
- 'lore'     — unlock a cosmetic lore entry

The pool is hand-authored — easy to extend later. Stored as plain Python
tuples so we don't need a config language.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

# --- Combat vignettes (lightweight CampSpec-shaped opponents) ---------------


@dataclass(frozen=True)
class RegionMob:
    name: str
    tier: int
    weak_to: str | None
    base_gold: int
    base_xp: int


# --- Region encounter pool ---------------------------------------------------


@dataclass(frozen=True)
class CombatEncounter:
    kind: str         # 'combat'
    flavor: str
    mob: RegionMob


@dataclass(frozen=True)
class TreasureEncounter:
    kind: str         # 'treasure'
    flavor: str
    base_gold: int
    bonus_drop: str | None   # e.g. 'mat' or 'fragment_t2'; None = gold only
    drop_chance: float       # 0.0..1.0


@dataclass(frozen=True)
class LoreEncounter:
    kind: str         # 'lore'
    flavor: str
    lore_key: str
    lore_text: str


Encounter = CombatEncounter | TreasureEncounter | LoreEncounter


REGIONS: dict[str, tuple[Encounter, ...]] = {
    "Demacia": (
        CombatEncounter(
            kind="combat",
            flavor="A renegade mage challenges you outside the Mageseeker barracks.",
            mob=RegionMob("Mageseeker Renegade", tier=2, weak_to="AD", base_gold=350, base_xp=60),
        ),
        TreasureEncounter(
            kind="treasure",
            flavor="You discover a Sentinel's lost cache, hidden in a hollow oak.",
            base_gold=300, bonus_drop="mat", drop_chance=0.5,
        ),
        LoreEncounter(
            kind="lore",
            flavor="An old knight recounts the founding of the Dauntless Vanguard.",
            lore_key="demacia.vanguard",
            lore_text=(
                "_The Dauntless Vanguard was forged in the Rune Wars — knights "
                "sworn to halt magic itself. Their oaths bind even kings._"
            ),
        ),
    ),
    "Noxus": (
        CombatEncounter(
            kind="combat",
            flavor="A Black Rose spy ambushes you in a back alley of Basilich.",
            mob=RegionMob("Black Rose Adept", tier=3, weak_to="AD", base_gold=600, base_xp=110),
        ),
        TreasureEncounter(
            kind="treasure",
            flavor="A defector hands you a sealed Noxian war chest.",
            base_gold=500, bonus_drop="fragment_t3", drop_chance=0.2,
        ),
        LoreEncounter(
            kind="lore",
            flavor="A scribe tells you how the Trifarix replaced the immortal throne.",
            lore_key="noxus.trifarix",
            lore_text=(
                "_When Boram Darkwill fell, three pillars rose to rule Noxus: "
                "Might, Vision, and Guile. None alone can claim the empire._"
            ),
        ),
    ),
    "Ionia": (
        CombatEncounter(
            kind="combat",
            flavor="A wayward spirit guardian tests your resolve under cherry blossoms.",
            mob=RegionMob("Wayward Spirit", tier=2, weak_to="AP", base_gold=400, base_xp=70),
        ),
        TreasureEncounter(
            kind="treasure",
            flavor="A village elder gifts you a jade prayer fragment.",
            base_gold=350, bonus_drop="fragment_t2", drop_chance=0.3,
        ),
        LoreEncounter(
            kind="lore",
            flavor="A blind monk speaks of the First Lands and balance.",
            lore_key="ionia.balance",
            lore_text=(
                "_The First Lands hum with spirit and matter intertwined. "
                "When balance is broken — invasion, magic, war — Ionia itself wakes._"
            ),
        ),
    ),
    "Piltover": (
        CombatEncounter(
            kind="combat",
            flavor="A hextech-armored enforcer mistakes you for a Zaunite saboteur.",
            mob=RegionMob("Enforcer", tier=2, weak_to="AP", base_gold=380, base_xp=65),
        ),
        TreasureEncounter(
            kind="treasure",
            flavor="A clocktower technician owes you a favor — and pays in crystallized hex.",
            base_gold=450, bonus_drop="mat", drop_chance=0.7,
        ),
        LoreEncounter(
            kind="lore",
            flavor="A clan elder tells the story of the Sun Gates.",
            lore_key="piltover.sun_gates",
            lore_text=(
                "_Piltover's wealth flows through the Sun Gates — colossal locks "
                "moving ships from Conqueror's Sea to Rising Tides. Whoever owns the gates owns trade._"
            ),
        ),
    ),
    "Zaun": (
        CombatEncounter(
            kind="combat",
            flavor="A Chem-Baron's enforcers corner you in the Sumps.",
            mob=RegionMob("Chem-Baron Goon", tier=3, weak_to="AD", base_gold=550, base_xp=100),
        ),
        TreasureEncounter(
            kind="treasure",
            flavor="A grey-bag of contraband shimmer — sell quickly.",
            base_gold=600, bonus_drop="corruption_stack", drop_chance=1.0,
        ),
        LoreEncounter(
            kind="lore",
            flavor="A scuttling Chem-Baron's archivist speaks of the Sump Wars.",
            lore_key="zaun.sump",
            lore_text=(
                "_The Sump Wars carved the chem-barons their thrones — chemtech "
                "is power, and shimmer is currency. Zaun lives by both._"
            ),
        ),
    ),
    "Shurima": (
        CombatEncounter(
            kind="combat",
            flavor="A bandit chieftain blocks your path at the Oasis of the Dawn.",
            mob=RegionMob("Sun-Crazed Bandit", tier=3, weak_to=None, base_gold=600, base_xp=110),
        ),
        TreasureEncounter(
            kind="treasure",
            flavor="You unearth a sun disc shard buried in dunes.",
            base_gold=550, bonus_drop="fragment_t3", drop_chance=0.25,
        ),
        LoreEncounter(
            kind="lore",
            flavor="An archaeologist reads aloud from an Ascended-era stele.",
            lore_key="shurima.ascended",
            lore_text=(
                "_To Ascend was to be chosen — a mortal lifted by the Sun Disc into "
                "a god-blooded king. But the disc fell. And so did Shurima._"
            ),
        ),
    ),
    "Bilgewater": (
        CombatEncounter(
            kind="combat",
            flavor="A Buhru priest summons sea-things from the harbor.",
            mob=RegionMob("Tidecaller Initiate", tier=2, weak_to="AP", base_gold=400, base_xp=70),
        ),
        TreasureEncounter(
            kind="treasure",
            flavor="You barter a salvaged bounty mark for a sealed sea-chest.",
            base_gold=500, bonus_drop="soul", drop_chance=0.4,
        ),
        LoreEncounter(
            kind="lore",
            flavor="A salt-stained sailor tells you the truth about Nagakabouros.",
            lore_key="bilgewater.nagakabouros",
            lore_text=(
                "_Motion is life. The Mother Serpent does not sleep — she devours "
                "any soul who stops moving. Bilgewater understands._"
            ),
        ),
    ),
    "Targon": (
        CombatEncounter(
            kind="combat",
            flavor="A Solari zealot challenges your faith on the mountain path.",
            mob=RegionMob("Solari Zealot", tier=3, weak_to="AD", base_gold=600, base_xp=110),
        ),
        TreasureEncounter(
            kind="treasure",
            flavor="A celestial pilgrim shares their offerings.",
            base_gold=450, bonus_drop="fragment_t4", drop_chance=0.1,
        ),
        LoreEncounter(
            kind="lore",
            flavor="A Lunari hermit explains the long war beneath the mountain.",
            lore_key="targon.solari_lunari",
            lore_text=(
                "_The Solari worship the sun. The Lunari, the moon. Both are wrong. "
                "Both are right. Targon was never one truth._"
            ),
        ),
    ),
    "Freljord": (
        CombatEncounter(
            kind="combat",
            flavor="A frostguard berserker bars your path across the tundra.",
            mob=RegionMob("Frostguard Berserker", tier=3, weak_to="AP", base_gold=550, base_xp=100),
        ),
        TreasureEncounter(
            kind="treasure",
            flavor="You find an ice-locked Iceborn cache.",
            base_gold=500, bonus_drop="mat", drop_chance=0.8,
        ),
        LoreEncounter(
            kind="lore",
            flavor="A Winter's Claw shaman whispers of the Three Sisters.",
            lore_key="freljord.three_sisters",
            lore_text=(
                "_Avarosa unified. Serylda freed. Lissandra preserved — by sealing "
                "the Watchers in ice. One sister still walks, in shadow._"
            ),
        ),
    ),
    "Shadow Isles": (
        CombatEncounter(
            kind="combat",
            flavor="A Ruined sentinel rises from the Black Mist to meet you.",
            mob=RegionMob("Ruined Sentinel", tier=3, weak_to="AP", base_gold=600, base_xp=110),
        ),
        TreasureEncounter(
            kind="treasure",
            flavor="A trapped soul-lantern gives up its essence to your touch.",
            base_gold=400, bonus_drop="soul", drop_chance=1.0,
        ),
        LoreEncounter(
            kind="lore",
            flavor="A spectral librarian tells you of the Ruination.",
            lore_key="shadow_isles.ruination",
            lore_text=(
                "_When Viego sought to raise his queen, the magic shattered. "
                "Camavor's blessed isles fell to the Black Mist. Death stays — undeath remains._"
            ),
        ),
    ),
    "Bandle City": (
        CombatEncounter(
            kind="combat",
            flavor="A startled Yordle mistakes you for a thief — and brings friends.",
            mob=RegionMob("Yordle Tinker-Squad", tier=2, weak_to=None, base_gold=350, base_xp=60),
        ),
        TreasureEncounter(
            kind="treasure",
            flavor="A friendly Yordle trades you trinkets for tales.",
            base_gold=400, bonus_drop="mat", drop_chance=0.9,
        ),
        LoreEncounter(
            kind="lore",
            flavor="A wandering Yordle explains the Veil that hides their city.",
            lore_key="bandle.veil",
            lore_text=(
                "_Bandle City is not where you'd look. It is between. Mortals "
                "stumble in by accident, and stumble out forgetting they did._"
            ),
        ),
    ),
}


def regions_list() -> list[str]:
    return list(REGIONS.keys())


def pick_encounter(region: str, rng: random.Random | None = None) -> Encounter:
    rng = rng or random
    pool = REGIONS.get(region)
    if not pool:
        raise KeyError(f"Unknown region: {region}")
    return rng.choice(pool)
