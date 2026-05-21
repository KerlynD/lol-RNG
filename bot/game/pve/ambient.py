"""Ambient encounter pool — what kinds of surprise mobs appear."""
from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class AmbientSpec:
    key: str
    name: str
    tier: int
    weak_to: str | None
    base_gold: int
    base_xp: int
    flavor: str


AMBIENT_POOL: dict[str, AmbientSpec] = {
    "gromp_ambush": AmbientSpec(
        key="gromp_ambush",
        name="Gromp Ambush",
        tier=1,
        weak_to=None,
        base_gold=120,
        base_xp=15,
        flavor="A Gromp leaps from the brush at you!",
    ),
    "raptor_pack": AmbientSpec(
        key="raptor_pack",
        name="Raptor Pack",
        tier=1,
        weak_to="AD",
        base_gold=120,
        base_xp=15,
        flavor="A pack of Raptors circles you, screeching.",
    ),
    "voidling_stalker": AmbientSpec(
        key="voidling_stalker",
        name="Voidling Stalker",
        tier=2,
        weak_to=None,
        base_gold=250,
        base_xp=40,
        flavor="A Voidling tendril erupts from the ground.",
    ),
    "shadow_isles_wraith": AmbientSpec(
        key="shadow_isles_wraith",
        name="Black Mist Wraith",
        tier=2,
        weak_to="AP",
        base_gold=220,
        base_xp=35,
        flavor="A wraith drifts toward you through the Black Mist.",
    ),
    "noxian_skirmisher": AmbientSpec(
        key="noxian_skirmisher",
        name="Noxian Skirmisher",
        tier=2,
        weak_to="AD",
        base_gold=200,
        base_xp=30,
        flavor="A Noxian skirmisher demands tribute — or blood.",
    ),
    "ionian_assassin": AmbientSpec(
        key="ionian_assassin",
        name="Rogue Ionian Assassin",
        tier=3,
        weak_to=None,
        base_gold=400,
        base_xp=70,
        flavor="A rogue Ionian assassin draws her blade.",
    ),
}


def pick_ambient(rng: random.Random | None = None) -> AmbientSpec:
    rng = rng or random
    return rng.choice(list(AMBIENT_POOL.values()))
