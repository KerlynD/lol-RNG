"""Settings cog — user toggles + admin channel configuration."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries
from bot.tasks.ambient_events import CONFIG_AMBIENT_CHANNEL
from bot.utils.decorators import register_user
from bot.utils.embeds import info_embed


class SettingsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="settings", description="View your current settings.")
    @register_user
    async def settings(self, interaction: discord.Interaction) -> None:
        user = await queries.get_user(interaction.user.id)
        amb = "ON" if user.ambient_events_opt_in else "OFF"
        await interaction.response.send_message(
            embed=info_embed(
                f"**Ambient events:** {amb}\n"
                f"Toggle with `/ambient-toggle opt_in:true|false`."
            ),
            ephemeral=True,
        )

    @app_commands.command(
        name="admin-set-ambient-channel",
        description="(Admin) Designate this channel for random ambient encounters.",
    )
    @app_commands.default_permissions(administrator=True)
    @register_user
    async def admin_set_ambient_channel(self, interaction: discord.Interaction) -> None:
        await queries.set_config(CONFIG_AMBIENT_CHANNEL, str(interaction.channel_id))
        await interaction.response.send_message(
            embed=info_embed(f"Ambient encounters will spawn in <#{interaction.channel_id}>."),
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SettingsCog(bot))
