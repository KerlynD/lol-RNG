"""Region-scoped monster camps + wild champion encounters (v3 Phase 2).

`/hunt-camp` is no longer a single global pool — what you find depends on the
region you're standing in. Each region has a hand-authored set of monster
camps within its tier band, plus a chance of stumbling into a real champion
of that region (a "wild champion" — fight Teemo in Bandle City, etc.).

Pure data + pure functions. The wild-champion roster is resolved from the DB
at hunt time by the cog; this module only builds the CampSpec for it.
"""
from __future__ import annotations

import random
from typing import TYPE_CHECKING

from bot.game.pve.camps import CAMPS, CampSpec

if TYPE_CHECKING:
    from bot.db.queries import Champion


# A camp definition row: (slug, name, tier, weak_to, drops, weight)
_CampRow = tuple[str, str, int, "str | None", tuple[tuple[str, float], ...], float]


def _camp(region_key: str, row: _CampRow, flavor: str) -> tuple[CampSpec, float]:
    slug, name, tier, weak_to, drops, weight = row
    cd_lo = 25 + tier * 8
    cd_hi = cd_lo + 70
    spec = CampSpec(
        key=f"{region_key}:{slug}",
        name=name,
        tier=tier,
        cooldown_range=(cd_lo, cd_hi),
        base_gold=tier * 70,
        base_xp=tier * 11,
        weak_to=weak_to,
        drops=drops,
        flavor=flavor,
    )
    return spec, weight


# Per-region content. Each entry: (wild_champ_chance, [(camp_row, flavor), ...]).
# Tiers stay inside the region's danger band (see world/regions.py).
_M = (("mat", 0.25),)
_MS = (("mat", 0.3), ("soul", 0.2))
_MF5 = (("mat", 0.3), ("fragment_t5", 0.15))
_MF6 = (("mat", 0.3), ("fragment_t6", 0.12))

_REGION_DATA: dict[str, tuple[float, list[tuple[_CampRow, str]]]] = {
    "bandle_city": (0.20, [
        (("wolves", "Murk Wolves", 1, "AP", (("mat", 0.15),), 22.0),
         "Three Murk Wolves snarl from the undergrowth."),
        (("raptors", "Crimson Raptors", 1, "AD", (("mat", 0.15),), 22.0),
         "Raptors circle, their leader screeching."),
        (("thugs", "Yordle Thugs", 1, None, (("mat", 0.2),), 16.0),
         "A gang of yordle thugs blocks the mushroom path."),
        (("pixies", "Wicked Pixies", 2, "AP", _M, 12.0),
         "Wicked pixies giggle — their magic is anything but kind."),
        (("poros", "Poro Stampede", 1, None, (("mat", 0.1),), 10.0),
         "A poro stampede! Adorable, and somehow dangerous."),
        (("gromp", "Bramble Gromp", 2, None, _M, 8.0),
         "A bramble-crusted Gromp puffs up its spores."),
    ]),
    "demacia": (0.16, [
        (("bandits", "Highway Bandits", 2, "AD", _M, 22.0),
         "Bandits emerge from the petricite woods."),
        (("renegade", "Renegade Mage", 3, "AD", _M, 16.0),
         "A renegade mage, hunted by the Mageseekers, turns on you."),
        (("wolfpack", "Demacian Wolf Pack", 2, "AP", _M, 18.0),
         "A wolf pack drags down a stag — and notices you."),
        (("golem", "Petricite Golem", 3, None, _MS, 10.0),
         "A petricite golem grinds awake, magic-deadening stone."),
        (("deserter", "Deserter Knight", 3, "AD", _M, 12.0),
         "A disgraced knight bars the road, sword drawn."),
    ]),
    "freljord": (0.16, [
        (("trolls", "Ice Trolls", 3, "AD", _M, 22.0),
         "Iceborn trolls form a battle line, hefting frozen clubs."),
        (("frostwolf", "Frostguard Wolves", 3, "AP", _M, 18.0),
         "Frostguard wolves stalk you across the tundra."),
        (("revenant", "Iceborn Revenant", 4, None, _MS, 12.0),
         "An Iceborn revenant claws free of the permafrost."),
        (("yeti", "Rimefang Yeti", 4, "AD", _MS, 10.0),
         "A Rimefang yeti roars, its breath a blizzard."),
        (("scout", "Avarosan Scout", 3, None, _M, 16.0),
         "An Avarosan scout mistakes you for a Winter's Claw raider."),
    ]),
    "ionia": (0.16, [
        (("spirit", "Wandering Spirit", 4, "AP", _M, 22.0),
         "A wandering spirit tests your resolve beneath the blossoms."),
        (("occupier", "Noxian Occupier", 4, "AD", _M, 18.0),
         "A Noxian occupier patrol refuses to let you pass."),
        (("vastayan", "Vastayan Hunter", 4, None, _M, 16.0),
         "A Vastayan hunter shadows you through the bamboo."),
        (("corrupted", "Corrupted Monk", 5, "AP", _MF5, 10.0),
         "A monk twisted by the Noxian invasion attacks without a word."),
        (("blossom", "Spirit Blossom Shade", 5, None, _MF5, 9.0),
         "A Spirit Blossom shade beckons — to follow is to fight."),
    ]),
    "piltover_zaun": (0.16, [
        (("chemthug", "Chem-Thug", 2, None, _M, 22.0),
         "A shimmer-addled chem-thug lunges from a Zaun alley."),
        (("sumpsnipe", "Sump Snipe Pack", 2, "AD", _M, 18.0),
         "Sump snipes swarm out of the grey ooze."),
        (("enforcer", "Enforcer Squad", 3, None, _M, 16.0),
         "A Piltover enforcer squad mistakes you for a saboteur."),
        (("drone", "Rogue Hextech Drone", 4, "AP", _MS, 11.0),
         "A malfunctioning hextech drone locks onto you."),
        (("shimmerbeast", "Shimmer-Beast", 5, "AD", _MF5, 8.0),
         "A shimmer-beast — once human — drags itself toward you."),
    ]),
    "bilgewater": (0.16, [
        (("cultist", "Buhru Cultists", 5, "AP", _M, 22.0),
         "Buhru cultists chant the name of the Mother Serpent."),
        (("hunter", "Rival Bounty Hunter", 5, "AD", _MF5, 18.0),
         "A rival bounty hunter decides your head is worth coin."),
        (("harpoon", "Harpoon Crew", 5, None, _M, 16.0),
         "A harpoon crew corners you on the rotting docks."),
        (("kraken", "Krakenspawn", 6, "AD", _MF6, 10.0),
         "Krakenspawn boil up from the harbor depths."),
        (("mistwalker", "Mistwalker", 6, "AP", _MF6, 9.0),
         "A mistwalker drifts from the Black Mist, hungry."),
    ]),
    "shadow_isles": (0.16, [
        (("wraith", "Mist Wraiths", 5, "AP", _M, 22.0),
         "Mist wraiths coil out of the Black Mist."),
        (("knight", "Ruined Knight", 5, "AD", _MF5, 18.0),
         "A Ruined knight, armor weeping shadow, raises its blade."),
        (("hound", "Spectral Hounds", 5, None, _MS, 16.0),
         "Spectral hounds bay — the Harrowing never truly ends."),
        (("revenant", "Harrowing Revenant", 6, "AP", _MF6, 10.0),
         "A Harrowing revenant remembers, faintly, being alive."),
        (("horror", "Black Mist Horror", 6, None, _MF6, 9.0),
         "Something vast and wrong unfolds from the mist."),
    ]),
    "ixtal": (0.16, [
        (("wisp", "Elemental Wisps", 5, "AP", _M, 22.0),
         "Elemental wisps flare hostile in the deep jungle."),
        (("sentry", "Yun Tal Sentry", 5, "AD", _MF5, 18.0),
         "A Yun Tal sentry steps from the leaves, blade humming."),
        (("stalker", "Jungle Stalker", 5, None, _MS, 16.0),
         "A jungle stalker has been following you for miles."),
        (("saurian", "Ancient Saurian", 6, "AD", _MF6, 10.0),
         "An ancient saurian, older than Ixaocan, bellows."),
        (("construct", "Druidic Construct", 6, "AP", _MF6, 9.0),
         "A construct of living wood and stone grinds toward you."),
    ]),
    "shurima": (0.15, [
        (("raider", "Sand Raiders", 6, "AD", _MF6, 22.0),
         "Sand raiders sweep down the dune on hungry mounts."),
        (("xersai", "Xer'Sai Burrower", 6, None, _MS, 18.0),
         "A Xer'Sai burrower erupts from beneath the sand."),
        (("husk", "Ascended Husk", 6, "AP", _MF6, 14.0),
         "An Ascended husk, hollowed by millennia, turns its gaze on you."),
        (("guardian", "Sun Disc Guardian", 7, None, (("mat", 0.3), ("soul", 0.3)), 8.0),
         "A Sun Disc guardian ignites with ancient solar fury."),
        (("voidtouched", "Void-Touched Ascendant", 7, None, _MS, 7.0),
         "An Ascendant, half-claimed by the Void, shrieks a broken hymn."),
    ]),
    "noxus": (0.15, [
        (("legionnaire", "Trifarian Legionnaire", 7, "AD", _MS, 24.0),
         "A Trifarian legionnaire sizes you up — strength is the only law."),
        (("cabalist", "Black Rose Cabalist", 7, "AP", _MS, 20.0),
         "A Black Rose cabalist weaves a spell behind a porcelain smile."),
        (("reckoner", "Reckoner Champion", 7, None, (("mat", 0.3), ("soul", 0.35)), 12.0),
         "A Reckoner champion steps into the arena dust to face you."),
    ]),
    "targon": (0.15, [
        (("templar", "Solari Templar", 7, "AD", _MS, 22.0),
         "A Solari templar's sunfire blade flares to life."),
        (("lunari", "Lunari Shade", 7, "AP", _MS, 20.0),
         "A Lunari shade slips between moonbeams, dagger first."),
        (("pilgrim", "Aspect-Touched Pilgrim", 7, None, _MS, 14.0),
         "A pilgrim, eyes full of starlight, will not yield the path."),
        (("colossus", "Starforged Colossus", 7, None, (("mat", 0.3), ("soul", 0.4)), 9.0),
         "A colossus of starforged stone wakes atop the peak."),
    ]),
    "void": (0.12, [
        (("swarm", "Voidling Swarm", 7, None, _MS, 24.0),
         "A voidling swarm chitters out of a tear in the world."),
        (("burrower", "Void Burrower", 8, "AD", _MS, 16.0),
         "A Void burrower the size of a ship surfaces beneath you."),
        (("herald", "Voidborn Herald", 8, "AP", (("soul", 0.5),), 10.0),
         "A Voidborn herald speaks, and reality flinches."),
    ]),
}


# Pre-built per-region pools: region_key -> (wild_champ_chance, [(CampSpec, weight)]).
REGION_POOLS: dict[str, tuple[float, list[tuple[CampSpec, float]]]] = {
    region_key: (
        wild_chance,
        [_camp(region_key, row, flavor) for row, flavor in rows],
    )
    for region_key, (wild_chance, rows) in _REGION_DATA.items()
}


# Buff camps + elemental drakes — rare jackpot encounters. They reuse the
# legacy CampSpecs from camps.py (Red/Blue Brambleback drop red/blue buff;
# drakes drop a dragon soul). Kept out of v3 region pools by the v3 rewrite —
# re-seeded here into thematically-fitting regions at low weight.
_SPECIAL_PLACEMENTS: dict[str, list[tuple[str, float]]] = {
    "freljord": [("red_brambleback", 2.0)],
    "ionia": [("blue_sentinel", 2.0)],
    "piltover_zaun": [("blue_sentinel", 2.0)],
    "ixtal": [
        ("red_brambleback", 1.5),
        ("drake_cloud", 0.5), ("drake_ocean", 0.5), ("drake_mountain", 0.5),
    ],
    "shurima": [
        ("drake_infernal", 0.5), ("drake_chemtech", 0.5), ("drake_hextech", 0.5),
    ],
}

for _region_key, _specials in _SPECIAL_PLACEMENTS.items():
    _camps = REGION_POOLS[_region_key][1]
    for _camp_key, _weight in _specials:
        _camps.append((CAMPS[_camp_key], _weight))


def wild_champ_chance(region_key: str) -> float:
    entry = REGION_POOLS.get(region_key)
    return entry[0] if entry else 0.0


def roll_region_encounter(
    region_key: str, rng: random.Random | None = None
) -> CampSpec | None:
    """Pick a weighted monster camp for the region, or None if region unknown."""
    rng = rng or random
    entry = REGION_POOLS.get(region_key)
    if not entry:
        return None
    camps = entry[1]
    specs = [c for c, _ in camps]
    weights = [w for _, w in camps]
    return rng.choices(specs, weights=weights, k=1)[0]


def wild_champion_camp(champ: Champion) -> CampSpec:
    """Build a CampSpec for a wild champion encounter.

    Champions hit harder than monsters of the same tier — the payout reflects
    that, and a same-tier fragment can drop.
    """
    frag_tier = min(champ.tier, 6)
    return CampSpec(
        key=f"wild:{champ.id}",
        name=champ.name,
        tier=champ.tier,
        cooldown_range=(60, 160),
        base_gold=champ.tier * 150,
        base_xp=champ.tier * 24,
        weak_to=None,
        drops=(("mat", 0.5), (f"fragment_t{frag_tier}", 0.15)),
        flavor=f"You round a bend and come face to face with **{champ.name}**!",
    )
