"""PvP cog — /attack, /spy."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries
from bot.game.pvp_flow import attempt_pvp
from bot.utils.decorators import register_user
from bot.utils.embeds import (
    TIER_NAME,
    failure_embed,
    info_embed,
    skirmish_embed,
)

log = logging.getLogger(__name__)


class PvP(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="attack", description="Challenge another player to a multi-round skirmish.")
    @app_commands.describe(target="Who to attack.")
    @register_user
    async def attack(self, interaction: discord.Interaction, target: discord.Member) -> None:
        if target.bot:
            await interaction.response.send_message(
                embed=failure_embed("You can't attack a bot."), ephemeral=True
            )
            return

        outcome = await attempt_pvp(interaction.user.id, target.id)
        if outcome.error:
            await interaction.response.send_message(
                embed=failure_embed(outcome.error), ephemeral=True
            )
            return
        if outcome.immune:
            await interaction.response.send_message(
                embed=failure_embed(f"{target.display_name} is wreathed in Lamb's Respite. Untouchable.")
            )
            return
        if outcome.capped:
            await interaction.response.send_message(
                embed=failure_embed(f"{target.display_name} is rested. No more attacks today.")
            )
            return
        if outcome.auto_tied:
            await interaction.response.send_message(
                embed=info_embed(
                    f"{target.display_name}'s Kindred passive triggers — your blade catches on Wolf's teeth and the exchange ends in nothing."
                )
            )
            return

        await interaction.response.send_message(
            embed=skirmish_embed(
                interaction.user, target, outcome.skirmish, outcome.gold_transferred
            )
        )

    @app_commands.command(
        name="spy",
        description="View a player you're hunting (granted by /eternal-hunt).",
    )
    @app_commands.describe(target="The player you've marked.")
    @register_user
    async def spy(self, interaction: discord.Interaction, target: discord.Member) -> None:
        # /eternal-hunt sets a cooldown row with action_key f'_hunt:{target_id}' as a 7-day "grant"
        key = f"_hunt:{target.id}"
        remaining = await queries.check_cooldown(interaction.user.id, key)
        if remaining is None:
            await interaction.response.send_message(
                embed=failure_embed(
                    f"You aren't hunting {target.display_name}. Cast `/eternal-hunt` first."
                ),
                ephemeral=True,
            )
            return

        t_user = await queries.get_user(target.id)
        if t_user is None:
            await interaction.response.send_message(
                embed=failure_embed("Target has no profile."), ephemeral=True
            )
            return
        t_load = await queries.get_loadout(target.id)
        t_inv = await queries.get_inventory(target.id)

        loadout_str = "\n".join(
            f"  Slot {e.slot}: {e.champion.name} ({TIER_NAME[e.champion.tier]}, {e.champion.damage_type})"
            for e in t_load
        ) or "  _empty_"
        shields_str = (
            f"  Physical: {t_inv.get('shield_physical', 0)}\n"
            f"  Magic:    {t_inv.get('shield_magic', 0)}\n"
            f"  Aegis:    {t_inv.get('aegis', 0)}\n"
            f"  Stasis:   {t_inv.get('stasis', 0)}"
        )
        desc = (
            f"Watching **{target.display_name}** (expires <t:{int((discord.utils.utcnow().timestamp() + remaining))}:R>)\n\n"
            f"**Level:** {t_user.level}    **Gold:** {t_user.gold:,}\n\n"
            f"**Loadout:**\n{loadout_str}\n\n"
            f"**Shields:**\n{shields_str}"
        )
        await interaction.response.send_message(
            embed=discord.Embed(title="Eternal Hunt", description=desc, color=0x000000),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PvP(bot))
