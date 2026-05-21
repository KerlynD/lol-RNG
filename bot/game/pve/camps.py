"""PVE camp registry + weighted random encounter pool (PRD v2)."""
from __future__ import annotations

import random
from dataclasses import dataclass

# A camp's cooldown range is the player-local respawn after both
# engaging AND backing out. Drawn uniformly between low and high.
@dataclass(frozen=True)
class CampSpec:
    key: str
    name: str
    tier: int
    cooldown_range: tuple[int, int]   # seconds
    base_gold: int
    base_xp: int
    weak_to: str | None               # 'AD' | 'AP' | None
    drops: tuple[tuple[str, float], ...] = ()  # (item_type, probability)
    flavor: str = ""


CAMPS: dict[str, CampSpec] = {
    "wolves": CampSpec(
        key="wolves", name="Murk Wolves", tier=1, cooldown_range=(60, 120),
        base_gold=60, base_xp=8, weak_to="AP",
        drops=(("mat", 0.15),),
        flavor="Three Murk Wolves snarl from the shadows.",
    ),
    "raptors": CampSpec(
        key="raptors", name="Raptors", tier=1, cooldown_range=(60, 120),
        base_gold=60, base_xp=8, weak_to="AD",
        drops=(("mat", 0.15),),
        flavor="Crimson Raptors circle, their leader eyeing you hungrily.",
    ),
    "krugs": CampSpec(
        key="krugs", name="Krugs", tier=1, cooldown_range=(90, 150),
        base_gold=80, base_xp=12, weak_to=None,
        drops=(("mat", 0.25),),
        flavor="An Ancient Krug rumbles awake, smaller stones flanking it.",
    ),
    "gromp": CampSpec(
        key="gromp", name="Gromp", tier=1, cooldown_range=(90, 150),
        base_gold=80, base_xp=12, weak_to=None,
        drops=(("mat", 0.25),),
        flavor="A massive Gromp puffs up its toxic spores.",
    ),
    "scuttler": CampSpec(
        key="scuttler", name="Rift Scuttler", tier=1, cooldown_range=(45, 90),
        base_gold=40, base_xp=5, weak_to=None,
        flavor="A nervous Rift Scuttler scuttles across your path.",
    ),
    "troll_camp": CampSpec(
        key="troll_camp", name="Freljord Troll Camp", tier=2, cooldown_range=(120, 180),
        base_gold=150, base_xp=25, weak_to="AD",
        drops=(("mat", 0.4),),
        flavor="Iceborn trolls form a battle line, hefting cracked clubs.",
    ),
    "voidling_nest": CampSpec(
        key="voidling_nest", name="Voidling Nest", tier=3, cooldown_range=(180, 240),
        base_gold=350, base_xp=60, weak_to=None,
        drops=(("soul", 0.3),),
        flavor="The earth ruptures — voidlings spill out, chittering.",
    ),
    "red_brambleback": CampSpec(
        key="red_brambleback", name="Red Brambleback", tier=2, cooldown_range=(240, 300),
        base_gold=400, base_xp=80, weak_to="AD",
        drops=(("red_buff", 1.0),),
        flavor="The Red Brambleback's eyes burn with elemental fury.",
    ),
    "blue_sentinel": CampSpec(
        key="blue_sentinel", name="Blue Sentinel", tier=2, cooldown_range=(240, 300),
        base_gold=400, base_xp=80, weak_to="AP",
        drops=(("blue_buff", 1.0),),
        flavor="The Blue Sentinel's azure runes pulse — defending its territory.",
    ),
    # Drake slot — actual drake picked uniformly inside the pool weight
    "drake_cloud": CampSpec(
        key="drake_cloud", name="Cloud Drake", tier=4, cooldown_range=(300, 300),
        base_gold=1500, base_xp=250, weak_to=None,
        drops=(("dragon_soul_cloud", 1.0), ("fragment_t3", 0.3)),
        flavor="A Cloud Drake spirals down, wind whipping the dust.",
    ),
    "drake_ocean": CampSpec(
        key="drake_ocean", name="Ocean Drake", tier=4, cooldown_range=(300, 300),
        base_gold=1500, base_xp=250, weak_to=None,
        drops=(("dragon_soul_ocean", 1.0), ("fragment_t3", 0.3)),
        flavor="An Ocean Drake surges from the mists, scales glistening.",
    ),
    "drake_mountain": CampSpec(
        key="drake_mountain", name="Mountain Drake", tier=4, cooldown_range=(300, 300),
        base_gold=1500, base_xp=250, weak_to=None,
        drops=(("dragon_soul_mountain", 1.0), ("fragment_t3", 0.3)),
        flavor="A Mountain Drake crashes down — stone splinters fly.",
    ),
    "drake_infernal": CampSpec(
        key="drake_infernal", name="Infernal Drake", tier=4, cooldown_range=(300, 300),
        base_gold=1500, base_xp=250, weak_to=None,
        drops=(("dragon_soul_infernal", 1.0), ("fragment_t3", 0.3)),
        flavor="The Infernal Drake roars, the air itself igniting.",
    ),
    "drake_chemtech": CampSpec(
        key="drake_chemtech", name="Chemtech Drake", tier=4, cooldown_range=(300, 300),
        base_gold=1500, base_xp=250, weak_to=None,
        drops=(("dragon_soul_chemtech", 1.0), ("fragment_t3", 0.3)),
        flavor="A Chemtech Drake oozes corrosive sludge from every scale.",
    ),
    "drake_hextech": CampSpec(
        key="drake_hextech", name="Hextech Drake", tier=4, cooldown_range=(300, 300),
        base_gold=1500, base_xp=250, weak_to=None,
        drops=(("dragon_soul_hextech", 1.0), ("fragment_t3", 0.3)),
        flavor="A Hextech Drake materializes in a cascade of blue runes.",
    ),
}


# Encounter pool: each row is (set_of_camp_keys, weight). When the random pick
# falls into a row, one camp from the set is chosen uniformly. This lets the
# 6 drakes share a single ~1% slot so each specific drake is ~0.16%.
ENCOUNTER_POOL: tuple[tuple[tuple[str, ...], float], ...] = (
    (("wolves",), 22.0),
    (("raptors",), 22.0),
    (("krugs",), 16.0),
    (("gromp",), 16.0),
    (("scuttler",), 10.0),
    (("troll_camp",), 6.0),
    (("voidling_nest",), 4.0),
    (("red_brambleback",), 1.5),
    (("blue_sentinel",), 1.5),
    (("drake_cloud", "drake_ocean", "drake_mountain",
      "drake_infernal", "drake_chemtech", "drake_hextech"), 1.0),
)


def roll_encounter(rng: random.Random | None = None) -> CampSpec:
    rng = rng or random
    rows = list(ENCOUNTER_POOL)
    bucket_weights = [w for _, w in rows]
    bucket_keys = [keys for keys, _ in rows]
    bucket = rng.choices(bucket_keys, weights=bucket_weights, k=1)[0]
    key = rng.choice(bucket)
    return CAMPS[key]


def cooldown_seconds(camp: CampSpec, rng: random.Random | None = None) -> int:
    rng = rng or random
    low, high = camp.cooldown_range
    if low >= high:
        return low
    return rng.randint(low, high)
