"""Adventure cog — /start-adventure (the way into the game) and /adventure.

v3 makes Runeterra a place: every player has a location, and the rest of the
bot is gated behind /start-adventure (see bot/utils/gating.py). /adventure is
the hub command — in Phase 1 it's a read-only dashboard; Travel, Quests and
folded Region Actions land in later phases.
"""
from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot.db import queries
from bot.game.world.regions import STARTING_REGION
from bot.utils.decorators import register_user
from bot.utils.embeds import (
    adventure_hub_embed,
    adventure_welcome_embed,
    info_embed,
)

log = logging.getLogger(__name__)


class Adventure(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="start-adventure",
        description="Begin your journey through Runeterra. Start here!",
    )
    @register_user
    async def start_adventure(self, interaction: discord.Interaction) -> None:
        user = await queries.get_user(interaction.user.id)
        if user is not None and user.adventure_started_at is not None:
            unlocked = await queries.list_unlocked_regions(interaction.user.id)
            await interaction.response.send_message(
                embeds=[
                    info_embed(
                        "Your adventure is already underway. Here's where you stand:"
                    ),
                    adventure_hub_embed(user, unlocked),
                ],
                ephemeral=True,
            )
            return

        await queries.start_adventure(interaction.user.id, STARTING_REGION)
        log.info("User %s started their adventure.", interaction.user.id)
        await interaction.response.send_message(embed=adventure_welcome_embed())

    @app_commands.command(
        name="adventure",
        description="Your adventure hub — where you are in Runeterra and what's next.",
    )
    @register_user
    async def adventure(self, interaction: discord.Interaction) -> None:
        user = await queries.get_user(interaction.user.id)
        unlocked = await queries.list_unlocked_regions(interaction.user.id)
        await interaction.response.send_message(
            embed=adventure_hub_embed(user, unlocked), ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Adventure(bot))
