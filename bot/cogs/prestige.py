"""Prestige cog — /prestige with confirmation flow."""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries
from bot.game.leveling import LEVEL_CAP
from bot.utils.decorators import register_user
from bot.utils.embeds import failure_embed

log = logging.getLogger(__name__)


class PrestigeConfirm(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.confirmed: bool = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id

    @discord.ui.button(label="Prestige", style=discord.ButtonStyle.danger, emoji="✨")
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        self.confirmed = True
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(content="Prestige cancelled.", view=self)
        self.stop()


class Prestige(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="prestige",
        description="Reset XP and champion collection at Lv30 for a permanent boost.",
    )
    @register_user
    async def prestige(self, interaction: discord.Interaction) -> None:
        user = await queries.get_user(interaction.user.id)
        if user.level < LEVEL_CAP:
            await interaction.response.send_message(
                embed=failure_embed(
                    f"You need Level {LEVEL_CAP} to prestige (you're {user.level})."
                ),
                ephemeral=True,
            )
            return

        owned = await queries.list_owned(interaction.user.id)
        confirm_embed = discord.Embed(
            title="✨ Prestige Confirmation",
            description=(
                f"You will **reset to Level 1** and **lose all {len(owned)} owned champions** "
                f"(loadout also cleared).\n\n"
                f"You will **keep:** Gold, Roll Tokens, Fragments, Shields, Mats, Souls.\n\n"
                f"You will **gain:**\n"
                f"• +5% Gold income (permanent, stacks)\n"
                f"• Improved Death-tier roll rate (×2 per prestige stack)\n"
                f"• Prestige counter → **{user.prestige + 1}**\n\n"
                f"This cannot be undone."
            ),
            color=0xFFD700,
        )
        view = PrestigeConfirm(interaction.user.id)
        await interaction.response.send_message(embed=confirm_embed, view=view, ephemeral=True)
        await view.wait()

        if not view.confirmed:
            return

        await queries.reset_for_prestige(interaction.user.id)
        new_user = await queries.get_user(interaction.user.id)
        await interaction.followup.send(
            embed=discord.Embed(
                title=f"✨ Prestige {new_user.prestige}",
                description=(
                    f"You shed your legend and begin anew, **<@{interaction.user.id}>**.\n\n"
                    f"Permanent Gold bonus: **+{5 * new_user.prestige}%**\n"
                    f"Death-tier multiplier: **×{2 ** new_user.prestige}**"
                ),
                color=0xFFD700,
            )
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Prestige(bot))
