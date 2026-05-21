from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries

log = logging.getLogger(__name__)


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ping", description="Check bot latency.")
    async def ping(self, interaction: discord.Interaction) -> None:
        latency_ms = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"Pong — {latency_ms} ms.", ephemeral=True)

    @app_commands.command(name="dbcheck", description="Verify DB connectivity and champion seed.")
    async def dbcheck(self, interaction: discord.Interaction) -> None:
        try:
            count = await queries.champion_count()
        except Exception as e:
            log.exception("dbcheck failed")
            await interaction.response.send_message(f"DB error: {e}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"DB OK. Champions seeded: **{count}**.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))
