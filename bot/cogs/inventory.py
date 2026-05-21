"""Inventory cog — /inventory, /profile, /champions, /shields."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries
from bot.utils.decorators import register_user
from bot.utils.embeds import (
    TIER_COLOR,
    TIER_NAME,
    inventory_embed,
    profile_embed,
)


class Inventory(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="inventory", description="View your gold, tokens, shields, fragments, and items.")
    @register_user
    async def inventory(self, interaction: discord.Interaction) -> None:
        items = await queries.get_inventory(interaction.user.id)
        user = await queries.get_user(interaction.user.id)
        embed = inventory_embed(items)
        embed.add_field(name="Gold", value=f"{user.gold:,}", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="shields", description="Quick view of your shield stockpile.")
    @register_user
    async def shields(self, interaction: discord.Interaction) -> None:
        items = await queries.get_inventory(interaction.user.id)
        lines = [
            f"Physical: **{items.get('shield_physical', 0)}**",
            f"Magic:    **{items.get('shield_magic', 0)}**",
            f"Aegis:    **{items.get('aegis', 0)}**",
            f"Stasis:   **{items.get('stasis', 0)}**",
        ]
        await interaction.response.send_message(
            embed=discord.Embed(
                title="Shields", description="\n".join(lines), color=0x607D8B
            ),
            ephemeral=True,
        )

    @app_commands.command(name="profile", description="Your level, XP, prestige, gold, and unlocks.")
    @register_user
    async def profile(self, interaction: discord.Interaction) -> None:
        user = await queries.get_user(interaction.user.id)
        owned = await queries.list_owned(interaction.user.id)
        loadout = await queries.get_loadout(interaction.user.id)
        embed = profile_embed(user, champ_count=len(owned), loadout_size=len(loadout))
        embed.title = f"{interaction.user.display_name}'s profile"
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="champions", description="List the champions you own, grouped by tier.")
    @register_user
    async def champions(self, interaction: discord.Interaction) -> None:
        owned = await queries.list_owned(interaction.user.id)
        if not owned:
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="Collection",
                    description="You haven't rolled any champions yet. Try `/roll`!",
                    color=0x607D8B,
                ),
                ephemeral=True,
            )
            return

        # Group by tier (already sorted by tier desc, name).
        groups: dict[int, list[str]] = {}
        for oc in owned:
            lbl = oc.champion.name + (" 🔒" if oc.locked else "")
            groups.setdefault(oc.champion.tier, []).append(lbl)

        embed = discord.Embed(
            title=f"Collection ({len(owned)} champions)",
            color=0x3F51B5,
        )
        for tier in sorted(groups.keys(), reverse=True):
            embed.add_field(
                name=f"Tier {tier} — {TIER_NAME[tier]} ({len(groups[tier])})",
                value=", ".join(groups[tier]) or "—",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Inventory(bot))
