"""Standardized Discord embed builders. Populated as cogs land."""
from __future__ import annotations

import discord

TIER_COLOR: dict[int, int] = {
    1: 0x9E9E9E,
    2: 0x4CAF50,
    3: 0x2196F3,
    4: 0x9C27B0,
    5: 0xFFC107,
    6: 0xFF5722,
    7: 0x000000,
}


def tier_embed(title: str, description: str, tier: int) -> discord.Embed:
    return discord.Embed(
        title=title,
        description=description,
        color=TIER_COLOR.get(tier, 0xCCCCCC),
    )
