"""The Runeterra world map — regions, the travel graph, and tier gating.

Pure data + pure functions. No Discord, no DB. This module is the source of
truth for where a player can go and what they can roll/fight there.

The travel graph is locked from the canonical map of Runeterra:

    Bandle City — Demacia — Freljord — { Noxus, Ionia }
    Ionia — Piltover & Zaun — { Ixtal, Bilgewater }
    Bilgewater — { Shadow Isles, Ixtal }
    Ixtal — Shurima — { Noxus, Targon }
    The Void — hidden, reachable only from Shurima / Targon

All edges are bidirectional: once a region is unlocked you may travel back and
forth. Danger (the region tier band) is the real gate, not the map.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

# Champions only exist up to Tier 7 (Death). Some regions are lore-rated higher
# (Targon is "T7-T10" because Aurelion Sol) but rolls/fights clamp to this.
MAX_CHAMPION_TIER = 7


@dataclass(frozen=True)
class Region:
    key: str
    display: str
    tier_min: int                    # lore/danger band lower bound
    tier_max: int                    # lore/danger band upper bound
    neighbors: tuple[str, ...]       # region keys reachable by /travel
    champ_regions: tuple[str, ...]   # champions.json `region` values mapped here
    blurb: str
    hidden: bool = False             # not drawn on the normal map (the Void)


WORLD: dict[str, Region] = {
    "bandle_city": Region(
        key="bandle_city", display="Bandle City", tier_min=1, tier_max=2,
        neighbors=("demacia",), champ_regions=("Bandle City",),
        blurb=(
            "A hidden dimension within the great Bandle Tree — the kindest "
            "corner of all creation, and where every adventure begins."
        ),
    ),
    "demacia": Region(
        key="demacia", display="Demacia", tier_min=2, tier_max=3,
        neighbors=("bandle_city", "freljord"), champ_regions=("Demacia",),
        blurb="A proud kingdom of law and light, ever wary of magic.",
    ),
    "freljord": Region(
        key="freljord", display="Freljord", tier_min=3, tier_max=4,
        neighbors=("demacia", "noxus", "ionia"), champ_regions=("Freljord",),
        blurb="An unforgiving expanse of ice ruled by three warring sisters.",
    ),
    "ionia": Region(
        key="ionia", display="Ionia", tier_min=4, tier_max=5,
        neighbors=("freljord", "piltover_zaun"), champ_regions=("Ionia",),
        blurb="The First Lands, where spirit and matter intertwine.",
    ),
    "piltover_zaun": Region(
        key="piltover_zaun", display="Piltover & Zaun", tier_min=2, tier_max=5,
        neighbors=("ionia", "ixtal", "bilgewater"),
        champ_regions=("Piltover", "Zaun"),
        blurb="The City of Progress above, the chem-fueled undercity below.",
    ),
    "bilgewater": Region(
        key="bilgewater", display="Bilgewater", tier_min=5, tier_max=6,
        neighbors=("piltover_zaun", "shadow_isles", "ixtal"),
        champ_regions=("Bilgewater",),
        blurb="A lawless port of bounty hunters, sea-monsters, and the Mist.",
    ),
    "shadow_isles": Region(
        key="shadow_isles", display="Shadow Isles", tier_min=5, tier_max=6,
        neighbors=("bilgewater",), champ_regions=("Shadow Isles",),
        blurb="Cursed islands wreathed in the Black Mist. Death does not stay.",
    ),
    "ixtal": Region(
        key="ixtal", display="Ixtal", tier_min=5, tier_max=6,
        neighbors=("piltover_zaun", "bilgewater", "shurima"),
        champ_regions=("Ixtal",),
        blurb="A hidden jungle nation guarding the elemental arts.",
    ),
    "shurima": Region(
        key="shurima", display="Shurima", tier_min=6, tier_max=7,
        neighbors=("ixtal", "noxus", "targon", "void"),
        champ_regions=("Shurima",),
        blurb="A fallen desert empire of Ascended god-warriors.",
    ),
    "noxus": Region(
        key="noxus", display="Noxus", tier_min=7, tier_max=9,
        neighbors=("freljord", "shurima"), champ_regions=("Noxus",),
        blurb="A brutal expansionist empire where strength is the only law.",
    ),
    "targon": Region(
        key="targon", display="Targon", tier_min=7, tier_max=10,
        neighbors=("shurima", "void"), champ_regions=("Targon",),
        blurb="A cosmic mountain scraping the stars, where Aspects walk.",
    ),
    "void": Region(
        key="void", display="The Void", tier_min=8, tier_max=9,
        neighbors=("shurima", "targon"), champ_regions=("Void", "The Void"),
        blurb="A hungering nothing beneath reality. It only wants.",
        hidden=True,
    ),
}

# Everyone begins here.
STARTING_REGION = "bandle_city"

# Display / walk order for menus.
REGION_ORDER: tuple[str, ...] = (
    "bandle_city", "demacia", "freljord", "ionia", "piltover_zaun",
    "bilgewater", "shadow_isles", "ixtal", "shurima", "noxus", "targon", "void",
)


def get_region(region_key: str | None) -> Region | None:
    if not region_key:
        return None
    return WORLD.get(region_key)


def tier_band_label(region: Region) -> str:
    """Human-readable danger band, e.g. 'T1–T2' or 'T7–T10'."""
    return f"T{region.tier_min}–T{region.tier_max}"


def roll_tier_cap(region_key: str | None) -> int:
    """Highest champion tier that may be rolled while standing in this region.

    This is what stops a day-one player rolling a Legendary. Unknown / missing
    region falls back to the global max (no cap).
    """
    region = get_region(region_key)
    if region is None:
        return MAX_CHAMPION_TIER
    return min(region.tier_max, MAX_CHAMPION_TIER)


def is_adjacent(a: str, b: str) -> bool:
    region = get_region(a)
    return region is not None and b in region.neighbors


def region_distance(a: str, b: str) -> int:
    """Shortest number of /travel hops between two regions, or -1 if no path.

    Used by the (Phase 3) travel-cost formula: farther regions cost more gold.
    """
    if a == b:
        return 0
    if a not in WORLD or b not in WORLD:
        return -1
    seen = {a}
    queue: deque[tuple[str, int]] = deque([(a, 0)])
    while queue:
        node, dist = queue.popleft()
        for nxt in WORLD[node].neighbors:
            if nxt == b:
                return dist + 1
            if nxt not in seen:
                seen.add(nxt)
                queue.append((nxt, dist + 1))
    return -1


def _validate_graph() -> None:
    """Module-load sanity check: every edge is bidirectional and well-formed."""
    for key, region in WORLD.items():
        assert region.key == key, f"WORLD key mismatch: {key}"
        for nb in region.neighbors:
            assert nb in WORLD, f"{key} points at unknown region {nb}"
            assert key in WORLD[nb].neighbors, (
                f"travel graph not symmetric: {key}->{nb} but not {nb}->{key}"
            )


_validate_graph()
