"""Map champion display names to Riot Data Dragon image URLs.

Most champion API IDs are just `Name.replace(" ", "").replace("'", "")` but
Riot has a handful of quirky exceptions (Wukong → MonkeyKing). This module
hard-codes those + provides a default transformation.
"""
from __future__ import annotations

# Special cases where the API ID differs from a naive name-strip.
_SPECIAL = {
    "Wukong": "MonkeyKing",
    "Nunu & Willump": "Nunu",
    "Renata Glasc": "Renata",
    "Dr. Mundo": "DrMundo",
    "Cho'Gath": "Chogath",
    "Kha'Zix": "Khazix",
    "Vel'Koz": "Velkoz",
    "Kog'Maw": "KogMaw",
    "Kai'Sa": "Kaisa",
    "Rek'Sai": "RekSai",
    "Bel'Veth": "Belveth",
    "K'Sante": "KSante",
    "LeBlanc": "Leblanc",
    "Jarvan IV": "JarvanIV",
    "Aurelion Sol": "AurelionSol",
    "Master Yi": "MasterYi",
    "Lee Sin": "LeeSin",
    "Twisted Fate": "TwistedFate",
    "Miss Fortune": "MissFortune",
    "Tahm Kench": "TahmKench",
    "Xin Zhao": "XinZhao",
}


def riot_id(name: str) -> str:
    """Convert a display name to the Riot champion API ID."""
    if name in _SPECIAL:
        return _SPECIAL[name]
    # Strip apostrophes and spaces, preserve case.
    return name.replace(" ", "").replace("'", "").replace(".", "")


def tile_url(name: str) -> str:
    """Small (200×200) champion tile — good for embed thumbnails."""
    return f"https://cdn.communitydragon.org/latest/champion/{riot_id(name)}/square"


def splash_url(name: str) -> str:
    """Centered card-style splash, smaller than full splash."""
    return f"https://cdn.communitydragon.org/latest/champion/{riot_id(name)}/splash-art/centered"
